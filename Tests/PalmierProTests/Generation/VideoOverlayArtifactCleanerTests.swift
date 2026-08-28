import Testing
@testable import PalmierPro

@Suite("video overlay artifact cleaner")
struct VideoOverlayArtifactCleanerTests {
    @Test func detectsThePurplePanelColor() {
        #expect(VideoOverlayArtifactCleaner.purplePixel(255, 145, 180))
        #expect(!VideoOverlayArtifactCleaner.purplePixel(145, 145, 145))
        #expect(!VideoOverlayArtifactCleaner.purplePixel(220, 180, 90))
    }

    @Test func scalesPanelBoundsIndependentlyForWidthAndHeight() {
        let portrait = VideoOverlayArtifactCleaner.panelBounds(width: 720, height: 1280)
        #expect(portrait.left == 18)
        #expect(portrait.top == 450)
        #expect(portrait.right == 702)
        #expect(portrait.bottom == 856)

        let doubled = VideoOverlayArtifactCleaner.panelBounds(width: 1440, height: 2560)
        #expect(doubled.left == 36)
        #expect(doubled.top == 900)
        #expect(doubled.right == 1404)
        #expect(doubled.bottom == 1712)
    }

    @Test func cleanupKeyIsStableForPersistedGenerationJobs() {
        #expect(VideoOverlayArtifactCleaner.postprocessKey == "purple_panel_artifact_v1")
    }

    @Test func limitsRepairToThePanelBorder() {
        let bounds = VideoOverlayArtifactCleaner.panelBounds(width: 720, height: 1280)
        #expect(VideoOverlayArtifactCleaner.isPanelBorderPixel(x: 300, y: 452, bounds: bounds))
        #expect(VideoOverlayArtifactCleaner.isPanelBorderPixel(x: 20, y: 600, bounds: bounds))
        #expect(!VideoOverlayArtifactCleaner.isPanelBorderPixel(x: 300, y: 600, bounds: bounds))
    }
}
