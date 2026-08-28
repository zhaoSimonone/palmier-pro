import MCP
import Testing
@testable import PalmierPro

@Suite("remove_overlays tool")
struct RemoveOverlaysToolTests {
    @Test func exposesUserIntentSchema() throws {
        let tool = try #require(ToolDefinitions.mcpServer.first { $0.name == .removeOverlays })
        #expect(ToolDefinitions.inAppAgent.contains { $0.name == .removeOverlays })
        guard case .object(let schema) = tool.mcpSchemaValue,
              case .object(let properties) = schema["properties"],
              case .array(let required) = schema["required"] else {
            Issue.record("remove_overlays must expose an MCP object schema")
            return
        }

        #expect(properties["mediaRef"]?.objectValue?["type"]?.stringValue == "string")
        #expect(properties["instruction"] != nil)
        #expect(properties["sourceClipId"] != nil)
        #expect(required.compactMap(\.stringValue) == ["mediaRef"])
    }

    @Test func promptPreservesVideoAndTargetsOptionalDescription() {
        let base = RemoveOverlaysPrompt.make(instruction: nil)
        let described = RemoveOverlaysPrompt.make(instruction: "the lower-left watermark")

        #expect(base.contains("temporally consistent video inpainting"))
        #expect(base.contains("audio"))
        #expect(!base.contains("lower-left watermark"))
        #expect(described.hasPrefix(base))
        #expect(described.contains("the lower-left watermark"))
    }

    @Test func usesTheKnownArtifactCleanupForGeneratedResults() {
        #expect(RemoveOverlaysPrompt.postprocess == VideoOverlayArtifactCleaner.postprocessKey)
    }
}
