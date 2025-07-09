"""
Test Gemini video handling for Google AI Studio vs Vertex AI

This tests the fix for the issue where Google AI Studio Gemini models
(gemini-2.5-flash, gemini-2.5-pro, gemini-2.0-flash) were incorrectly
trying to convert video URLs to base64.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from litellm.llms.gemini.chat.transformation import GoogleAIStudioGeminiConfig
from litellm.llms.vertex_ai.gemini.transformation import _gemini_convert_messages_with_history
from litellm.types.llms.openai import AllMessageValues
from typing import List


class TestGeminiVideoHandling:
    """Test video handling differences between Google AI Studio and Vertex AI Gemini"""

    def test_google_ai_studio_does_not_convert_video_to_base64(self):
        """Test that Google AI Studio Gemini doesn't convert video URLs to base64"""
        
        config = GoogleAIStudioGeminiConfig()
        
        # Test message with video URL
        messages: List[AllMessageValues] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "What's in this video?"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "https://storage.googleapis.com/cloud-samples-data/video/animals.mp4"
                        }
                    }
                ]
            }
        ]
        
        # Mock convert_to_anthropic_image_obj to track if it's called
        with patch('litellm.llms.gemini.chat.transformation.convert_to_anthropic_image_obj') as mock_convert:
            # Mock _gemini_convert_messages_with_history to avoid full processing
            with patch('litellm.llms.gemini.chat.transformation._gemini_convert_messages_with_history') as mock_convert_history:
                mock_convert_history.return_value = []
                
                # Call the transform method
                config._transform_messages(messages)
                
                # Verify convert_to_anthropic_image_obj was NOT called for video
                mock_convert.assert_not_called()
                
                # Verify the video URL was preserved in the message
                video_element = messages[0]["content"][1]
                assert video_element["image_url"]["url"] == "https://storage.googleapis.com/cloud-samples-data/video/animals.mp4"

    def test_google_ai_studio_still_converts_images_to_base64(self):
        """Test that Google AI Studio Gemini still converts image URLs to base64"""
        
        config = GoogleAIStudioGeminiConfig()
        
        # Test with image URL
        messages: List[AllMessageValues] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "What's in this image?"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "https://example.com/image.jpg"
                        }
                    }
                ]
            }
        ]
        
        with patch('litellm.llms.gemini.chat.transformation.convert_to_anthropic_image_obj') as mock_convert:
            with patch('litellm.llms.gemini.chat.transformation.convert_generic_image_chunk_to_openai_image_obj') as mock_openai_convert:
                with patch('litellm.llms.gemini.chat.transformation._gemini_convert_messages_with_history') as mock_convert_history:
                    mock_convert_history.return_value = []
                    mock_convert.return_value = {"type": "base64", "media_type": "image/jpeg", "data": "base64data"}
                    mock_openai_convert.return_value = "data:image/jpeg;base64,base64data"
                    
                    config._transform_messages(messages)
                    
                    # Verify convert_to_anthropic_image_obj WAS called for image
                    mock_convert.assert_called_once()

    def test_various_video_formats_not_converted(self):
        """Test that various video formats are not converted to base64"""
        
        config = GoogleAIStudioGeminiConfig()
        
        video_formats = [
            ("https://example.com/video.mp4", "video/mp4"),
            ("https://example.com/video.mov", "video/mov"),
            ("https://example.com/video.mpeg", "video/mpeg"),
            ("https://example.com/video.avi", "video/avi"),
            ("https://example.com/video.wmv", "video/wmv"),
            ("https://example.com/video.flv", "video/flv"),
            ("https://example.com/video.webm", "video/webm"),
        ]
        
        for video_url, expected_mime in video_formats:
            messages: List[AllMessageValues] = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": video_url
                            }
                        }
                    ]
                }
            ]
            
            with patch('litellm.llms.gemini.chat.transformation.convert_to_anthropic_image_obj') as mock_convert:
                with patch('litellm.llms.gemini.chat.transformation._gemini_convert_messages_with_history') as mock_convert_history:
                    mock_convert_history.return_value = []
                    
                    config._transform_messages(messages)
                    
                    # Should not convert any video format to base64
                    mock_convert.assert_not_called()

    def test_explicit_video_format_parameter(self):
        """Test handling of video with explicit format parameter"""
        
        config = GoogleAIStudioGeminiConfig()
        
        messages: List[AllMessageValues] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "https://example.com/myvideo",  # No extension
                            "format": "video/mp4"  # Explicit format
                        }
                    }
                ]
            }
        ]
        
        with patch('litellm.llms.gemini.chat.transformation.convert_to_anthropic_image_obj') as mock_convert:
            with patch('litellm.llms.gemini.chat.transformation._gemini_convert_messages_with_history') as mock_convert_history:
                mock_convert_history.return_value = []
                
                config._transform_messages(messages)
                
                # Should not convert video to base64 even with explicit format
                mock_convert.assert_not_called()

    def test_vertex_ai_gemini_preserves_video_urls(self):
        """Test that Vertex AI Gemini properly handles video URLs without conversion"""
        
        from litellm.llms.vertex_ai.gemini.transformation import _process_gemini_image
        
        # Test HTTPS video URL
        video_url = "https://storage.googleapis.com/cloud-samples-data/video/animals.mp4"
        result = _process_gemini_image(video_url)
        
        # Should create a file_data object with the URL
        assert "file_data" in result
        assert result["file_data"]["file_uri"] == video_url
        assert result["file_data"]["mime_type"] == "video/mp4"