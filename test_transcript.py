from youtube_transcript_api import YouTubeTranscriptApi

# Test video ID from a popular video that definitely has captions
video_id = "jNQXAC9IVRw"  # "Me at the zoo" - first YouTube video

try:
    subtitle = YouTubeTranscriptApi.get_transcript(video_id)
    text = ' '.join([line['text'] for line in subtitle])
    print(f"✅ SUCCESS! Got {len(text)} characters of transcript")
    print(f"First 200 chars: {text[:200]}")
except Exception as e:
    print(f"❌ FAILED: {e}")
