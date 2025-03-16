import os

def check_audio_folder(folder_path="90s Happy Hits"):
    """Check if the folder exists and contains audio files"""
    if not os.path.exists(folder_path):
        print(f"ERROR: Folder '{folder_path}' does not exist!")
        return
    
    print(f"Folder '{folder_path}' exists")
    
    # Check audio files
    audio_extensions = ['.mp3', '.wav', '.flac', '.ogg']
    files = os.listdir(folder_path)
    
    print(f"Total files in folder: {len(files)}")
    
    audio_files = [f for f in files if any(f.lower().endswith(ext) for ext in audio_extensions)]
    print(f"Audio files in folder: {len(audio_files)}")
    
    if audio_files:
        print("First few audio files:")
        for file in audio_files[:5]:
            print(f"  {file}")
    else:
        print("No audio files found in the folder!")

if __name__ == "__main__":
    check_audio_folder()