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
    
    // Add queue button to the now playing bar - place after the volume controls
    const nowPlayingContainer = document.querySelector('.now-playing-container');
    if (nowPlayingContainer) {
        // Check if queue button doesn't already exist
        if (!document.getElementById('queue-button')) {
            const queueButtonContainer = document.createElement('div');
            queueButtonContainer.className = 'queue-button-container';
            queueButtonContainer.innerHTML = `
                <button id="queue-button" class="control-button" title="Show Queue">
                    ≡  <!-- Simple text-based queue icon -->
                </button>
            `;
            nowPlayingContainer.appendChild(queueButtonContainer);
            
            // Add click handler
            document.getElementById('queue-button').addEventListener('click', toggleQueuePanel);
        }
    }
    
    // Add this code after the queue button creation

    // Create queue panel if it doesn't exist
    let queuePanel = document.getElementById('queue-panel');
    if (!queuePanel) {
        queuePanel = document.createElement('div');
        queuePanel.id = 'queue-panel';
        queuePanel.className = 'queue-panel';
        queuePanel.innerHTML = `
            <div class="queue-panel-header">
                <h3>Current Queue</h3>
                <button id="close-queue-panel" class="queue-close-button">&times;</button>
            </div>
            <div class="queue-panel-content">
                <div id="now-playing-track" class="queue-section">
                    <h4>Now Playing</h4>
                    <div id="current-queue-track" class="queue-track">
                        <!-- Current track will be displayed here -->
                    </div>
                </div>
                <div class="queue-section">
                    <h4>Coming Up Next</h4>
                    <div id="upcoming-tracks" class="queue-tracks-list">
                        <!-- Upcoming tracks will be displayed here -->
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(queuePanel);
        
        // Add close button event listener
        document.getElementById('close-queue-panel').addEventListener('click', closeQueuePanel);
    }
    
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
                document.dispatchEvent(new Event('queue-updated'));
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
        document.dispatchEvent(new Event('queue-updated'));
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

    // Expose queue management to window
    window.playEntirePlaylist = playEntirePlaylist;

    function playEntirePlaylist(tracks) {
        if (!tracks || !Array.isArray(tracks) || tracks.length === 0) {
            console.error('No tracks to play');
            return;
        }
        
        console.log(`Playing entire playlist with ${tracks.length} tracks`);
        
        // Clear current queue and replace with the playlist
        queue = [...tracks];
        currentTrackIndex = 0;
        
        // Start playing the first track
        const firstTrack = queue[0];
        playTrackById(firstTrack.id);
        
        // Show a notification
        const notification = document.createElement('div');
        notification.className = 'toast-notification';
        notification.textContent = `Playing playlist (${tracks.length} tracks)`;
        document.body.appendChild(notification);
        
        // Remove notification after 3 seconds
        setTimeout(() => {
            notification.classList.add('fade-out');
            setTimeout(() => document.body.removeChild(notification), 500);
        }, 3000);
        document.dispatchEvent(new Event('queue-updated'));
    }

    // Add these functions to handle the queue panel

    function toggleQueuePanel() {
        const queuePanel = document.getElementById('queue-panel');
        if (queuePanel) {
            queuePanel.classList.toggle('active');
            
            if (queuePanel.classList.contains('active')) {
                updateQueueDisplay();
            }
        }
    }

    function closeQueuePanel() {
        const queuePanel = document.getElementById('queue-panel');
        if (queuePanel) {
            queuePanel.classList.remove('active');
        }
    }

    function updateQueueDisplay() {
        // Update current track display
        const currentTrackElement = document.getElementById('current-queue-track');
        const upcomingTracksElement = document.getElementById('upcoming-tracks');
        
        if (!currentTrackElement || !upcomingTracksElement) return;
        
        if (queue.length > 0 && currentTrackIndex >= 0 && currentTrackIndex < queue.length) {
            const currentTrack = queue[currentTrackIndex];
            
            // Display current track
            currentTrackElement.innerHTML = `
                <div class="queue-track now-playing">
                    <div class="queue-track-art">
                        <img src="${currentTrack.album_art_url || '/static/images/default-album-art.png'}" 
                             alt="Album Art">
                    </div>
                    <div class="queue-track-info">
                        <div class="queue-track-title">${currentTrack.title || 'Unknown Title'}</div>
                        <div class="queue-track-artist">${currentTrack.artist || 'Unknown Artist'}</div>
                    </div>
                </div>
            `;
            
            // Display upcoming tracks
            let upcomingTracksHTML = '';
            for (let i = currentTrackIndex + 1; i < queue.length; i++) {
                const track = queue[i];
                upcomingTracksHTML += `
                    <div class="queue-track" data-index="${i}">
                        <div class="queue-track-art">
                            <img src="${track.album_art_url || '/static/images/default-album-art.png'}" 
                                 alt="Album Art">
                        </div>
                        <div class="queue-track-info">
                            <div class="queue-track-title">${track.title || 'Unknown Title'}</div>
                            <div class="queue-track-artist">${track.artist || 'Unknown Artist'}</div>
                        </div>
                        <div class="queue-track-controls">
                            <button class="queue-track-remove" data-index="${i}" title="Remove from queue">&times;</button>
                        </div>
                    </div>
                `;
            }
            
            upcomingTracksElement.innerHTML = upcomingTracksHTML || '<p>No more tracks in queue</p>';
            
            // Add event listeners to track elements
            document.querySelectorAll('.queue-track').forEach(trackElem => {
                if (!trackElem.classList.contains('now-playing')) {
                    trackElem.addEventListener('click', function() {
                        const index = parseInt(this.dataset.index);
                        if (!isNaN(index)) {
                            currentTrackIndex = index;
                            playTrackById(queue[index].id);
                            updateQueueDisplay();
                        }
                    });
                }
            });
            
            // Add event listeners to remove buttons
            document.querySelectorAll('.queue-track-remove').forEach(button => {
                button.addEventListener('click', function(e) {
                    e.stopPropagation();
                    const index = parseInt(this.dataset.index);
                    if (!isNaN(index) && index < queue.length) {
                        queue.splice(index, 1);
                        updateQueueDisplay();
                    }
                });
            });
        } else {
            currentTrackElement.innerHTML = '<p>No track currently playing</p>';
            upcomingTracksElement.innerHTML = '<p>Queue is empty</p>';
        }
    }

    // Call updateQueueDisplay whenever the queue changes or a track ends/starts
    // Add this to your existing code where you update the player
    document.addEventListener('queue-updated', updateQueueDisplay);
});