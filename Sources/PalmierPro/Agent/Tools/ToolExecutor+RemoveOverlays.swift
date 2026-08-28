import Foundation

enum RemoveOverlaysPrompt {
    static let postprocess = VideoOverlayArtifactCleaner.postprocessKey
    static let base = "Remove the specified non-diegetic overlays, logos, watermarks, captions, stickers, and obstructing graphic panels from the source video. Reconstruct every occluded pixel with temporally consistent video inpainting. Preserve the original subject identity, pose, motion, camera movement, lighting, background, framing, duration, frame timing, color, and audio. Do not crop, zoom, blur, freeze, replace, restyle, or otherwise change any unobstructed content."

    static func make(instruction: String?) -> String {
        let detail = instruction?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !detail.isEmpty else { return base }
        return "\(base) Target overlays only: \(detail). Do not treat this description as permission to modify anything else."
    }
}

extension ToolExecutor {
    func removeOverlays(_ editor: EditorViewModel, _ args: [String: Any]) throws -> ToolResult {
        guard AccountService.shared.isSignedIn else {
            throw ToolError("Removing overlays requires signing in to Palmier. Tell the user to sign in.")
        }
        guard AccountService.shared.hasCredits else {
            throw ToolError("Out of credits. Tell the user to add credits or subscribe to keep removing overlays.")
        }

        let mediaRef = try args.requireString("mediaRef").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !mediaRef.isEmpty else { throw ToolError("mediaRef must not be empty.") }
        let source = try asset(mediaRef, editor: editor, label: "Source video")
        guard source.type == .video else {
            throw ToolError("mediaRef must reference a video asset (got \(source.type.rawValue)).")
        }
        guard !source.isGenerating else {
            throw ToolError("Source video '\(source.name)' is still generating. Wait until it is ready before removing overlays.")
        }
        guard let model = VideoModelConfig.edit else {
            throw ToolError("No video edit model is available. Refresh the model catalog and try again.")
        }
        guard model.supportsSourceVideo, model.supportsPrompt else {
            throw ToolError("The available video edit model cannot accept a source video prompt.")
        }
        if model.paidOnly && !AccountService.shared.isPaid {
            throw ToolError("Model '\(model.id)' requires a paid plan. Subscribe before removing overlays.")
        }

        if let raw = args["instruction"], !(raw is String) {
            throw ToolError("instruction must be a string.")
        }
        if let instruction = args.string("instruction"),
           instruction.trimmingCharacters(in: .whitespacesAndNewlines).count > 1_000 {
            throw ToolError("instruction must be 1,000 characters or fewer.")
        }
        if let raw = args["name"], !(raw is String) {
            throw ToolError("name must be a string.")
        }
        if let raw = args["folder"], !(raw is String) {
            throw ToolError("folder must be a string.")
        }
        if let raw = args["sourceClipId"], !(raw is String) {
            throw ToolError("sourceClipId must be a string.")
        }
        if let raw = args["draft"], !isJSONBoolean(raw) {
            throw ToolError("draft must be true or false.")
        }

        var generationArgs: [String: Any] = [
            "sourceVideoMediaRef": source.id,
            "model": model.id,
            "prompt": RemoveOverlaysPrompt.make(instruction: args.string("instruction")),
            "name": args.string("name") ?? "\(source.name) - overlays removed",
        ]
        if let sourceClipId = args.string("sourceClipId") { generationArgs["sourceClipId"] = sourceClipId }
        if let name = args.string("name") { generationArgs["name"] = name }
        if let folder = args.string("folder") { generationArgs["folder"] = folder }
        if let draft = args["draft"] as? Bool { generationArgs["draft"] = draft }

        let prompt = generationArgs["prompt"] as? String ?? RemoveOverlaysPrompt.base
        return try generateVideoEdit(
            editor, generationArgs, prompt: prompt, model: model,
            operationLabel: "Overlay removal started",
            postprocess: RemoveOverlaysPrompt.postprocess
        )
    }
}
