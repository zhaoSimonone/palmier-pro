import AVFoundation
import CoreGraphics
import Foundation

/// Removes the purple rounded-panel artifact observed in source-video edit outputs.
/// This is a deterministic post-process for a known model failure, not semantic inpainting.
enum VideoOverlayArtifactCleaner {
    static let postprocessKey = "purple_panel_artifact_v1"

    struct ProcessingError: LocalizedError {
        let reason: String

        var errorDescription: String? { "Video artifact cleanup failed: \(reason)" }
    }

    @concurrent
    static func cleanIfNeeded(url: URL) async throws -> URL? {
        let asset = AVURLAsset(url: url)
        guard let track = try await asset.loadTracks(withMediaType: .video).first else {
            throw ProcessingError(reason: "video track unavailable")
        }
        let size = try await track.load(.naturalSize)
        let transform = try await track.load(.preferredTransform)
        guard transform.isIdentity else { return nil }
        let width = Int(abs(size.width).rounded())
        let height = Int(abs(size.height).rounded())
        guard width >= 2, height >= 2, width.isMultiple(of: 2), height.isMultiple(of: 2) else {
            return nil
        }
        let bounds = panelBounds(width: width, height: height)
        guard try await containsArtifact(
            url: url,
            width: width,
            height: height,
            bounds: bounds
        ) else { return nil }

        let videoOnlyURL = FileIO.temporaryFileURL(pathExtension: "mp4")
        do {
            let changed = try await processVideo(
                url: url,
                width: width,
                height: height,
                to: videoOnlyURL
            )
            guard changed else {
                try? FileManager.default.removeItem(at: videoOnlyURL)
                return nil
            }

            let outputURL = FileIO.temporaryFileURL(pathExtension: "mp4")
            do {
                try await muxOriginalAudio(
                    sourceURL: url,
                    videoURL: videoOnlyURL,
                    to: outputURL
                )
                try? FileManager.default.removeItem(at: videoOnlyURL)
                return outputURL
            } catch {
                try? FileManager.default.removeItem(at: videoOnlyURL)
                try? FileManager.default.removeItem(at: outputURL)
                throw error
            }
        } catch {
            try? FileManager.default.removeItem(at: videoOnlyURL)
            throw error
        }
    }

    nonisolated static func purplePixel(_ b: UInt8, _ g: UInt8, _ r: UInt8) -> Bool {
        r > 110 && b > 170 && Int(b) - Int(g) > 35 && Int(r) - Int(g) > 15
    }

    nonisolated static func isPanelBorderPixel(
        x: Int,
        y: Int,
        bounds: (left: Int, top: Int, right: Int, bottom: Int),
        thickness: Int = 20
    ) -> Bool {
        let top = y >= bounds.top && y <= bounds.top + thickness
        let bottom = y <= bounds.bottom && y >= bounds.bottom - thickness
        let left = x >= bounds.left && x <= bounds.left + thickness
        let right = x <= bounds.right && x >= bounds.right - thickness
        return (top || bottom || left || right)
            && x >= bounds.left && x <= bounds.right
            && y >= bounds.top && y <= bounds.bottom
    }

    nonisolated static func panelBounds(width: Int, height: Int) -> (left: Int, top: Int, right: Int, bottom: Int) {
        let horizontalScale = Double(width) / 720.0
        let verticalScale = Double(height) / 1280.0
        return (
            left: Int((18.0 * horizontalScale).rounded()),
            top: Int((450.0 * verticalScale).rounded()),
            right: Int((702.0 * horizontalScale).rounded()),
            bottom: Int((856.0 * verticalScale).rounded())
        )
    }

    @concurrent
    private static func containsArtifact(
        url: URL,
        width: Int,
        height: Int,
        bounds: (left: Int, top: Int, right: Int, bottom: Int)
    ) async throws -> Bool {
        let asset = AVURLAsset(url: url)
        guard let track = try await asset.loadTracks(withMediaType: .video).first else {
            throw ProcessingError(reason: "video track unavailable")
        }
        let reader = try AVAssetReader(asset: asset)
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
        ])
        output.alwaysCopiesSampleData = false
        guard reader.canAdd(output) else { throw ProcessingError(reason: "cannot configure artifact scan") }
        reader.add(output)
        guard reader.startReading() else {
            throw ProcessingError(reason: reader.error?.localizedDescription ?? "artifact scan could not start")
        }
        var samples = 0
        while samples < 48, let sample = output.copyNextSampleBuffer() {
            try Task.checkCancellation()
            if let buffer = CMSampleBufferGetImageBuffer(sample), hasPurplePixel(
                in: buffer,
                width: width,
                height: height,
                bounds: bounds
            ) {
                reader.cancelReading()
                return true
            }
            samples += 1
        }
        return false
    }

    nonisolated private static func hasPurplePixel(
        in buffer: CVPixelBuffer,
        width: Int,
        height: Int,
        bounds: (left: Int, top: Int, right: Int, bottom: Int)
    ) -> Bool {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { return false }
        let stride = CVPixelBufferGetBytesPerRow(buffer)
        let minX = max(1, bounds.left)
        let maxX = min(width - 2, bounds.right)
        let minY = max(1, bounds.top)
        let maxY = min(height - 2, bounds.bottom)
        for y in minY...maxY {
            for x in minX...maxX {
                let pixel = base.advanced(by: y * stride + x * 4).assumingMemoryBound(to: UInt8.self)
                if isPanelBorderPixel(x: x, y: y, bounds: bounds),
                   purplePixel(pixel[0], pixel[1], pixel[2]) { return true }
            }
        }
        return false
    }

    @concurrent
    private static func processVideo(url: URL, width: Int, height: Int, to outputURL: URL) async throws -> Bool {
        let asset = AVURLAsset(url: url)
        guard let track = try await asset.loadTracks(withMediaType: .video).first else {
            throw ProcessingError(reason: "video track unavailable")
        }
        let nominalFPS = try await track.load(.nominalFrameRate)
        let reader = try AVAssetReader(asset: asset)
        let readerOutput = AVAssetReaderTrackOutput(track: track, outputSettings: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
        ])
        readerOutput.alwaysCopiesSampleData = false
        guard reader.canAdd(readerOutput) else { throw ProcessingError(reason: "cannot configure video reader") }
        reader.add(readerOutput)

        let writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
        let writerInput = AVAssetWriterInput(mediaType: .video, outputSettings: [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: width,
            AVVideoHeightKey: height,
            AVVideoCompressionPropertiesKey: [
                AVVideoAverageBitRateKey: max(1_000_000, width * height * 5),
                AVVideoMaxKeyFrameIntervalKey: max(1, Int((nominalFPS > 0 ? nominalFPS : 30).rounded())),
            ],
        ])
        writerInput.expectsMediaDataInRealTime = false
        guard writer.canAdd(writerInput) else { throw ProcessingError(reason: "cannot configure video writer") }
        writer.add(writerInput)
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: writerInput,
            sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: width,
                kCVPixelBufferHeightKey as String: height,
                kCVPixelBufferCGImageCompatibilityKey as String: true,
                kCVPixelBufferCGBitmapContextCompatibilityKey as String: true,
            ]
        )

        guard reader.startReading() else {
            throw ProcessingError(reason: reader.error?.localizedDescription ?? "reader could not start")
        }
        guard writer.startWriting() else {
            throw ProcessingError(reason: writer.error?.localizedDescription ?? "writer could not start")
        }
        writer.startSession(atSourceTime: .zero)

        let bounds = panelBounds(width: width, height: height)
        var changed = false
        while let sample = readerOutput.copyNextSampleBuffer() {
            try Task.checkCancellation()
            guard let sourceBuffer = CMSampleBufferGetImageBuffer(sample),
                  let pool = adaptor.pixelBufferPool else {
                throw ProcessingError(reason: "pixel buffer unavailable")
            }
            while !writerInput.isReadyForMoreMediaData {
                try Task.checkCancellation()
                try await Task.sleep(for: .milliseconds(1))
            }
            var outputBuffer: CVPixelBuffer?
            guard CVPixelBufferPoolCreatePixelBuffer(nil, pool, &outputBuffer) == kCVReturnSuccess,
                  let outputBuffer else {
                throw ProcessingError(reason: "could not allocate output frame")
            }
            copyAndRepair(
                source: sourceBuffer,
                destination: outputBuffer,
                bounds: bounds,
                changed: &changed
            )
            let pts = CMSampleBufferGetPresentationTimeStamp(sample)
            guard adaptor.append(outputBuffer, withPresentationTime: pts) else {
                throw ProcessingError(reason: writer.error?.localizedDescription ?? "frame append failed")
            }
        }
        guard reader.status == .completed else {
            throw ProcessingError(reason: reader.error?.localizedDescription ?? "reader failed")
        }
        writerInput.markAsFinished()
        await writer.finishWriting()
        guard writer.status == .completed else {
            throw ProcessingError(reason: writer.error?.localizedDescription ?? "writer failed")
        }
        return changed
    }

    nonisolated private static func copyAndRepair(
        source: CVPixelBuffer,
        destination: CVPixelBuffer,
        bounds: (left: Int, top: Int, right: Int, bottom: Int),
        changed: inout Bool
    ) {
        CVPixelBufferLockBaseAddress(source, .readOnly)
        CVPixelBufferLockBaseAddress(destination, [])
        defer {
            CVPixelBufferUnlockBaseAddress(destination, [])
            CVPixelBufferUnlockBaseAddress(source, .readOnly)
        }
        guard let sourceBase = CVPixelBufferGetBaseAddress(source),
              let destinationBase = CVPixelBufferGetBaseAddress(destination) else { return }
        let width = CVPixelBufferGetWidth(source)
        let height = CVPixelBufferGetHeight(source)
        let sourceStride = CVPixelBufferGetBytesPerRow(source)
        let destinationStride = CVPixelBufferGetBytesPerRow(destination)
        for y in 0..<height {
            memcpy(
                destinationBase.advanced(by: y * destinationStride),
                sourceBase.advanced(by: y * sourceStride),
                min(sourceStride, destinationStride)
            )
        }

        let minX = max(1, bounds.left)
        let maxX = min(width - 2, bounds.right)
        let minY = max(1, bounds.top)
        let maxY = min(height - 2, bounds.bottom)
        for y in minY...maxY {
            for x in minX...maxX {
                let pixel = sourceBase.advanced(by: y * sourceStride + x * 4).assumingMemoryBound(to: UInt8.self)
                guard isPanelBorderPixel(x: x, y: y, bounds: bounds),
                      purplePixel(pixel[0], pixel[1], pixel[2]) else { continue }
                let distances = [
                    (abs(y - bounds.top), 0, y < (bounds.top + bounds.bottom) / 2 ? -4 : 4),
                    (abs(x - bounds.left), x < (bounds.left + bounds.right) / 2 ? -4 : 4, 0),
                ]
                let direction = distances.min { $0.0 < $1.0 } ?? (0, 0, 0)
                let sampleX = min(width - 1, max(0, x + direction.1))
                let sampleY = min(height - 1, max(0, y + direction.2))
                let replacement = sourceBase.advanced(by: sampleY * sourceStride + sampleX * 4).assumingMemoryBound(to: UInt8.self)
                let target = destinationBase.advanced(by: y * destinationStride + x * 4).assumingMemoryBound(to: UInt8.self)
                target[0] = replacement[0]
                target[1] = replacement[1]
                target[2] = replacement[2]
                target[3] = replacement[3]
                changed = true
            }
        }
    }

    @concurrent
    private static func muxOriginalAudio(sourceURL: URL, videoURL: URL, to outputURL: URL) async throws {
        let source = AVURLAsset(url: sourceURL)
        let video = AVURLAsset(url: videoURL)
        let videoTracks = try await video.loadTracks(withMediaType: .video)
        guard let videoTrack = videoTracks.first else { throw ProcessingError(reason: "cleaned video track unavailable") }
        let audioTracks = try await source.loadTracks(withMediaType: .audio)
        guard let audioTrack = audioTracks.first else {
            try FileIO.copyReplacingDestination(from: videoURL, to: outputURL)
            return
        }
        let videoDuration = try await video.load(.duration)
        let audioDuration = try await source.load(.duration)
        guard videoDuration.isNumeric, CMTimeCompare(videoDuration, .zero) > 0 else {
            throw ProcessingError(reason: "invalid media duration")
        }
        let audioDurationToCopy = min(videoDuration, audioDuration)
        guard audioDurationToCopy.isNumeric, CMTimeCompare(audioDurationToCopy, .zero) > 0 else {
            try FileIO.copyReplacingDestination(from: videoURL, to: outputURL)
            return
        }

        let composition = AVMutableComposition()
        guard let compositionVideo = composition.addMutableTrack(
            withMediaType: .video,
            preferredTrackID: kCMPersistentTrackID_Invalid
        ), let compositionAudio = composition.addMutableTrack(
            withMediaType: .audio,
            preferredTrackID: kCMPersistentTrackID_Invalid
        ) else { throw ProcessingError(reason: "could not create audio/video tracks") }
        try compositionVideo.insertTimeRange(.init(start: .zero, duration: videoDuration), of: videoTrack, at: .zero)
        try compositionAudio.insertTimeRange(.init(start: .zero, duration: audioDurationToCopy), of: audioTrack, at: .zero)
        guard let export = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetHighestQuality) else {
            throw ProcessingError(reason: "audio mux preset unavailable")
        }
        try await export.export(to: outputURL, as: .mp4)
    }
}

private extension CGAffineTransform {
    var isIdentity: Bool {
        self == .identity
    }
}
