import base64
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.api import gemini_routes
from src.core.models import Token
from src.services.generation_handler import GenerationHandler


class GeminiV1BetaUploadCompatTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_content_with_reference_image_uses_route_level_risky_upload_compat(self):
        upload_project_ids = []

        async def fake_upload_image(at, image_bytes, aspect_ratio="IMAGE_ASPECT_RATIO_LANDSCAPE", project_id=None):
            upload_project_ids.append(project_id)
            return "legacy-compatible-media-id"

        flow_client = type("FlowClientStub", (), {})()
        flow_client.clear_request_fingerprint = Mock()
        flow_client.prefill_remote_browser_pool = AsyncMock(return_value=False)
        flow_client.upload_image = AsyncMock(side_effect=fake_upload_image)
        flow_client.generate_image = AsyncMock(
            return_value=(
                {
                    "media": [
                        {
                            "name": "generated-media-id",
                            "image": {
                                "generatedImage": {
                                    "fifeUrl": "http://example.com/generated.jpg"
                                }
                            },
                        }
                    ]
                },
                "session-123",
                {},
            )
        )

        token = Token(
            id=7,
            st="test-st",
            at="test-at",
            email="tester@example.com",
            user_paygate_tier="PAYGATE_TIER_NOT_PAID",
        )

        token_manager = type("TokenManagerStub", (), {})()
        token_manager.ensure_valid_token = AsyncMock(return_value=token)
        token_manager.ensure_project_exists = AsyncMock(return_value="project-123")
        token_manager.record_error = AsyncMock()
        token_manager.record_usage = AsyncMock()
        token_manager.record_success = AsyncMock()

        load_balancer = type("LoadBalancerStub", (), {})()
        load_balancer.select_token = AsyncMock(return_value=token)
        load_balancer.release_pending = AsyncMock()

        db = type("DbStub", (), {})()
        db.add_request_log = AsyncMock(return_value=1)
        db.update_request_log = AsyncMock(return_value=None)

        handler = GenerationHandler(
            flow_client=flow_client,
            token_manager=token_manager,
            load_balancer=load_balancer,
            db=db,
            concurrency_manager=None,
            proxy_manager=None,
        )

        previous_handler = gemini_routes.generation_handler
        gemini_routes.set_generation_handler(handler)

        request = gemini_routes.GeminiGenerateContentRequest(
            contents=[
                gemini_routes.GeminiContent(
                    parts=[
                        gemini_routes.GeminiContentPart(text="edit this image"),
                        gemini_routes.GeminiContentPart(
                            inlineData={
                                "mimeType": "image/jpeg",
                                "data": base64.b64encode(b"fake-image").decode("utf-8"),
                            }
                        ),
                    ]
                )
            ],
            generationConfig=gemini_routes.GeminiGenerationConfig(
                imageConfig=gemini_routes.GeminiImageConfig(aspectRatio="1:1")
            ),
        )

        try:
            with patch.object(
                gemini_routes,
                "get_base64_from_image_url",
                AsyncMock(return_value=base64.b64encode(b"final-image").decode("utf-8")),
            ):
                response = await gemini_routes.gemini_generate_content(
                    model="gemini-3-pro-image-preview",
                    request=request,
                    _api_key="test-key",
                )
        finally:
            gemini_routes.set_generation_handler(previous_handler)

        payload = json.loads(response.body)
        inline_data = payload["candidates"][0]["content"]["parts"][0]["inlineData"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(upload_project_ids, [None])
        self.assertEqual(inline_data["mimeType"], "image/png")
        self.assertEqual(
            inline_data["data"],
            base64.b64encode(b"final-image").decode("utf-8"),
        )

        flow_client.clear_request_fingerprint.assert_called_once()
        flow_client.generate_image.assert_awaited_once()
        token_manager.record_usage.assert_awaited_once_with(token.id, is_video=False)
        token_manager.record_success.assert_awaited_once_with(token.id)
        token_manager.record_error.assert_not_awaited()
        load_balancer.release_pending.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
