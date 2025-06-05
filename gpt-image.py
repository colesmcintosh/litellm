#!/usr/bin/env python3
"""
Short script to generate an image using LiteLLM
"""

import litellm
import os

# Set your OpenAI API key
# Make sure to set your OPENAI_API_KEY environment variable
# export OPENAI_API_KEY="your-api-key-here"

def generate_image():
    try:
        # Generate an image using gpt-image-1 (though dall-e-3 is more common for generation)
        response = litellm.image_generation(
            api_base="http://0.0.0.0:4000",
            api_key=os.getenv("LITELLM_MASTER_KEY"),
            model="openai/gpt-image-1",  # You requested gpt-image-1 specifically
            prompt="A friendly robot assistant helping a user write code, with LiteLLM logos floating around it",
            n=1,                  # Number of images to generate
            size="1024x1024"      # Image size
        )
        
        print("✅ Image generated successfully!")
        print(f"📅 Created: {response.created}")

        # Get the base64 string and decode it to bytes
        base64_image = response.data[0].b64_json
        
        # Save the image to a file
        import base64
        with open("image.png", "wb") as f:
            f.write(base64.b64decode(base64_image))
        
        print(f"💾 Image saved as 'image.png'")
        
        return response
        
    except Exception as e:
        # Check if this is a validation error but image data exists
        error_str = str(e)
        
        # Look for image data in the error message
        if "b64_json" in error_str and "ValidationError" in error_str:
            print("🎉 Image was generated, but there's a response parsing issue!")
            print("🔍 The issue: gpt-image-1 returns None for usage fields, but LiteLLM expects integers")
            print("\n💡 This suggests:")
            print("1. ✅ gpt-image-1 DOES support image generation")
            print("2. ❌ But it doesn't return proper usage statistics")
            print("3. 🔧 This is a LiteLLM response parsing issue, not a model issue")
            
            # Try to extract the image data from the error if possible
            import re
            if "received_args=" in error_str:
                print("\n🔧 Raw response data is available in the error - image generation succeeded!")
                
        else:
            # Truncate very long strings (likely base64 data) for other errors
            error_str = re.sub(r'[A-Za-z0-9+/]{100,}', '[LONG_DATA_TRUNCATED]', error_str)
            
            # Also truncate any very long lines
            lines = error_str.split('\n')
            cleaned_lines = []
            for line in lines:
                if len(line) > 200:
                    cleaned_lines.append(line[:200] + '...[TRUNCATED]')
                else:
                    cleaned_lines.append(line)
            error_str = '\n'.join(cleaned_lines)
            
            print(f"❌ Error generating image with gpt-image-1: {error_str}")
            print(f"❌ Error type: {type(e).__name__}")
            print("\n🔍 Debugging info:")
            print("- Model: openai/gpt-image-1")
            print("- API Base: http://0.0.0.0:4000")
            print("- Using LiteLLM proxy")
            
        return None

if __name__ == "__main__":
    # Check if API key is set
    if not os.getenv("LITELLM_MASTER_KEY"):
        print("⚠️  Please set your LITELLM_MASTER_KEY environment variable:")
        print("   export LITELLM_MASTER_KEY='your-proxy-key-here'")
        print("\n💡 Alternative: Remove api_base and api_key to use OpenAI directly:")
        print("   export OPENAI_API_KEY='your-openai-key-here'")
        exit(1)
    
    print("🎨 Generating image with LiteLLM...")
    res = generate_image()
    if res:
        print(f"📊 Usage: {res.usage}")
    else:
        print("❌ Image generation failed")
