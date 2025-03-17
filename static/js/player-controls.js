// Player controls functionality

document.addEventListener('DOMContentLoaded', function() {
    // DOM elements
    const audioPlayer = document.getElementById('audio-player');
    const nowPlayingBar = document.getElementById('now-playing-bar');
    const nowPlayingArt = document.getElementById('now-playing-art');
    const nowPlayingTitle = document.getElementById('now-playing-title');
    const nowPlayingArtist = document.getElementById('now-playing-artist');
    const playPauseButton = document.getElementById('play-pause');
    const prevButton = document.getElementById('prev-track');
    const nextButton = document.getElementById('next-track');
    const progressBar = document.querySelector('.progress-bar');
    const progressFill = document.getElementById('progress-fill');
    const currentTimeDisplay = document.getElementById('current-time');
    const totalTimeDisplay = document.getElementById('total-time');
    const volumeSlider = document.getElementById('volume-slider');
    const muteButton = document.getElementById('mute-button');
    
    // Queue and current track state
    let queue = [];
    let currentTrackIndex = -1;
    let isPlaying = false;
    let lastVolume = 0.7; // Store volume level for mute/unmute
    
    // Initialize volume
    if (audioPlayer && volumeSlider) {
        audioPlayer.volume = volumeSlider.value;
    }
    
    // Event listeners
    if (playPauseButton) {
        playPauseButton.addEventListener('click', togglePlayPause);
    }
    
    if (prevButton) {
        prevButton.addEventListener('click', playPreviousTrack);
    }
    
    if (nextButton) {
        nextButton.addEventListener('click', playNextTrack);
    }
    
    if (progressBar) {
        progressBar.addEventListener('click', function(e) {
            const percent = e.offsetX / progressBar.offsetWidth;
            seekToPercent(percent);
        });
    }
    
    if (volumeSlider) {
        volumeSlider.addEventListener('input', function() {
            setVolume(this.value);
        });
    }
    
    if (muteButton) {
        muteButton.addEventListener('click', toggleMute);
    }
    
    if (audioPlayer) {
        // Update progress as audio plays
        audioPlayer.addEventListener('timeupdate', updateProgress);
        
        // When track ends
        audioPlayer.addEventListener('ended', function() {
            playNextTrack();
        });
        
        // Handle loading metadata (duration, etc.)
        audioPlayer.addEventListener('loadedmetadata', function() {
            updateTotalTime();
        });
        
        // Handle errors
        audioPlayer.addEventListener('error', function(e) {
            console.error('Audio error:', e);
            playNextTrack(); // Skip to next track on error
        });
    }
    
    // Expose the play track function to the window
    window.playTrack = playTrackById;
    
    // Player Functions
    function playTrackById(trackId) {
        console.log(`Playing track ID: ${trackId}`);
        
        // Fetch track info
        fetch(`/track/${trackId}`)
            .then(response => response.json())
            .then(track => {
                if (track.error) {
                    console.error(`Error loading track: ${track.error}`);
                    return;
                }
                
                // Show the now playing bar
                nowPlayingBar.classList.add('active');
                
                // Set audio source
                audioPlayer.src = `/stream/${trackId}`;
                
                // Update UI
                updateNowPlayingInfo(track);
                
                // Play the audio
                audioPlayer.play()
                    .then(() => {
                        isPlaying = true;
                        updatePlayPauseButton();
                    })
                    .catch(err => {
                        console.error('Error playing track:', err);
                    });
                
                // Update queue if not already part of it
                if (!queue.some(t => t.id === track.id)) {
                    queue.push(track);
                    currentTrackIndex = queue.length - 1;
                } else {
                    // Find track in queue
                    currentTrackIndex = queue.findIndex(t => t.id === track.id);
                }
            })
            .catch(error => {
                console.error('Error fetching track data:', error);
            });
    }
    
    function updateNowPlayingInfo(track) {
        // Update track info
        if (nowPlayingTitle) nowPlayingTitle.textContent = track.title || 'Unknown Title';
        if (nowPlayingArtist) nowPlayingArtist.textContent = track.artist || 'Unknown Artist';
        
        // Update album art
        if (nowPlayingArt) {
            if (track.album_art_url) {
                nowPlayingArt.src = `/albumart/${encodeURIComponent(track.album_art_url)}`;
                nowPlayingArt.onerror = function() {
                    this.src = '/static/images/default-album-art.png';
                };
            } else {
                nowPlayingArt.src = '/static/images/default-album-art.png';
            }
        }
        
        // Update document title
        document.title = `${track.title} - ${track.artist} | PUMP`;
    }
    
    function togglePlayPause() {
        if (!audioPlayer) return;
        
        if (audioPlayer.paused) {
            audioPlayer.play();
            isPlaying = true;
        } else {
            audioPlayer.pause();
            isPlaying = false;
        }
        
        updatePlayPauseButton();
    }
    
    function updatePlayPauseButton() {
        if (!playPauseButton) return;
        
        if (isPlaying) {
            playPauseButton.innerHTML = '⏸';
            playPauseButton.title = 'Pause';
        } else {
            playPauseButton.innerHTML = '▶';
            playPauseButton.title = 'Play';
        }
    }
    
    function playPreviousTrack() {
        if (queue.length === 0) return;
        
        // If we're more than 3 seconds into the track, restart it
        if (audioPlayer.currentTime > 3) {
            audioPlayer.currentTime = 0;
            return;
        }
        
        // Go to previous track if it exists
        if (currentTrackIndex > 0) {
            currentTrackIndex--;
            const prevTrack = queue[currentTrackIndex];
            playTrackById(prevTrack.id);
        } else {
            // Restart current track if it's the first one
            audioPlayer.currentTime = 0;
        }
    }
    
    function playNextTrack() {
        if (queue.length === 0) return;
        
        if (currentTrackIndex < queue.length - 1) {
            currentTrackIndex++;
            const nextTrack = queue[currentTrackIndex];
            playTrackById(nextTrack.id);
        } else {
            // End of queue, could loop or stop
            audioPlayer.pause();
            isPlaying = false;
            updatePlayPauseButton();
        }
    }
    
    function updateProgress() {
        if (!audioPlayer || !progressFill || !currentTimeDisplay) return;
        
        const currentTime = audioPlayer.currentTime;
        const duration = audioPlayer.duration || 0;
        
        // Update progress bar
        if (duration > 0) {
            const percent = (currentTime / duration) * 100;
            progressFill.style.width = `${percent}%`;
        }
        
        // Update time display
        currentTimeDisplay.textContent = formatTime(currentTime);
    }
    
    function updateTotalTime() {
        if (!audioPlayer || !totalTimeDisplay) return;
        
        const duration = audioPlayer.duration || 0;
        totalTimeDisplay.textContent = formatTime(duration);
    }
    
    function seekToPercent(percent) {
        if (!audioPlayer) return;
        
        const duration = audioPlayer.duration || 0;
        if (duration > 0) {
            audioPlayer.currentTime = percent * duration;
        }
    }
    
    function formatTime(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
    }
    
    function setVolume(volume) {
        if (!audioPlayer || !muteButton) return;
        
        audioPlayer.volume = volume;
        lastVolume = volume;
        
        // Update mute button appearance based on volume level
        if (parseFloat(volume) === 0) {
            muteButton.textContent = '🔇';
        } else if (parseFloat(volume) < 0.5) {
            muteButton.textContent = '🔉';
        } else {
            muteButton.textContent = '🔊';
        }
    }
    
    function toggleMute() {
        if (!audioPlayer || !volumeSlider || !muteButton) return;
        
        if (audioPlayer.volume > 0) {
            // Store current volume and mute
            lastVolume = audioPlayer.volume;
            setVolume(0);
            volumeSlider.value = 0;
        } else {
            // Restore previous volume
            setVolume(lastVolume || 0.7);
            volumeSlider.value = lastVolume || 0.7;
        }
    }
});