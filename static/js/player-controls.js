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
    const progressBar = document.querySelector('.now-playing-bar .progress-bar');
    const progressFill = document.getElementById('progress-fill');
    const currentTimeDisplay = document.getElementById('current-time');
    const totalTimeDisplay = document.getElementById('total-time');
    const volumeSlider = document.getElementById('volume-slider');
    const muteButton = document.getElementById('mute-button');
    const likeButton = document.getElementById('like-track');
    
    // Show the now playing bar by default (it's already in the DOM)
    if (nowPlayingBar) {
        // Keep the 'empty' class but make sure it's visible
        nowPlayingBar.classList.remove('active');
        nowPlayingBar.classList.add('empty');
    }

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
    
    // Event listeners - this is the key fix for the play/pause button
    if (playPauseButton) {
        console.log('Adding click event to play/pause button');
        playPauseButton.addEventListener('click', function() {
            console.log('Play/Pause button clicked');
            togglePlayPause();
        });
    } else {
        console.error('Play/pause button not found in the DOM');
    }
    
    // Add remaining event listeners
    if (prevButton) {
        prevButton.addEventListener('click', playPreviousTrack);
    }
    
    if (nextButton) {
        nextButton.addEventListener('click', playNextTrack);
    }
    
    if (progressBar) {
        // Single click functionality
        progressBar.addEventListener('click', function(e) {
            e.preventDefault(); // Prevent any default behavior
            const rect = progressBar.getBoundingClientRect();
            const clickX = e.clientX - rect.left;
            const percent = clickX / progressBar.offsetWidth;
            seekToPercent(percent);
        });
        
        // Add drag functionality for a smoother experience
        let isDragging = false; // Moved outside to be accessible to all handlers
        
        progressBar.addEventListener('mousedown', function(e) {
            e.preventDefault(); // Prevent any default behavior
            if (e.button !== 0) return; // Only handle left clicks
            
            // Set dragging to true
            isDragging = true;
            progressBar.classList.add('dragging'); // Add class for visual feedback
            
            // Initial seek based on click position
            const rect = progressBar.getBoundingClientRect();
            const clickX = e.clientX - rect.left;
            const percent = clickX / progressBar.offsetWidth;
            seekToPercent(percent);
            
            // Handle mouse move for continuous seeking during drag
            function handleMouseMove(e) {
                if (!isDragging) return;
                
                const rect = progressBar.getBoundingClientRect();
                const moveX = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
                const percent = moveX / progressBar.offsetWidth;
                
                // Update visual progress without seeking on every move
                if (progressFill) {
                    progressFill.style.width = `${percent * 100}%`;
                }
                
                // Update time display during drag
                if (currentTimeDisplay && audioPlayer) {
                    const newTime = percent * audioPlayer.duration;
                    currentTimeDisplay.textContent = formatTime(newTime);
                }
            }
            
            // Handle mouse up to end dragging and perform final seek
            function handleMouseUp(e) {
                if (!isDragging) return;
                
                // Set dragging to false
                isDragging = false;
                progressBar.classList.remove('dragging'); // Remove class
                
                // Final seek position
                const rect = progressBar.getBoundingClientRect();
                const finalX = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
                const percent = finalX / progressBar.offsetWidth;
                seekToPercent(percent);
                
                // Remove event listeners when done
                document.removeEventListener('mousemove', handleMouseMove);
                document.removeEventListener('mouseup', handleMouseUp);
            }
            
            // Add event listeners for drag operations - these were missing
            document.addEventListener('mousemove', handleMouseMove);
            document.addEventListener('mouseup', handleMouseUp);
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

        // Important: Update button state when play/pause state changes
        audioPlayer.addEventListener('play', function() {
            isPlaying = true;
            updatePlayPauseButton();
        });
        
        audioPlayer.addEventListener('pause', function() {
            isPlaying = false;
            updatePlayPauseButton();
        });
    }
    
    // Expose the play track function to the window
    window.playTrack = playTrackById;
    
    // Player Functions
    window.currentTrackId = window.currentTrackId || null;

    function playTrackById(trackId, autoplay = true, startTime = 0) {
        console.log(`Playing track ID: ${trackId} (autoplay: ${autoplay}, startTime: ${startTime})`);
        
        // Fetch track info
        fetch(`/track/${trackId}`)
            .then(response => response.json())
            .then(track => {
                if (track.error) {
                    console.error(`Error loading track: ${track.error}`);
                    return;
                }
                
                // Show the now playing bar as active (not empty)
                if (nowPlayingBar) {
                    nowPlayingBar.classList.remove('empty');
                    nowPlayingBar.classList.add('active');
                }
                
                // Show the now playing bar
                nowPlayingBar.classList.add('active');
                
                // Set audio source
                audioPlayer.src = `/stream/${trackId}`;
                
                // Set current track ID
                window.currentTrackId = trackId;
                
                // Update UI
                updateNowPlayingInfo(track);
                
                // Set the current time if provided
                if (startTime > 0) {
                    audioPlayer.currentTime = startTime;
                }
                
                // Play the audio if autoplay is true
                if (autoplay) {
                    audioPlayer.play()
                        .then(() => {
                            isPlaying = true;
                            updatePlayPauseButton();
                        })
                        .catch(err => {
                            console.error('Error playing track:', err);
                        });
                } else {
                    // Just load but don't play
                    isPlaying = false;
                    updatePlayPauseButton();
                }
                
                // Update queue if not already part of it
                if (!queue.some(t => t.id === track.id)) {
                    queue.push(track);
                    currentTrackIndex = queue.length - 1;
                } else {
                    // Find track in queue
                    currentTrackIndex = queue.findIndex(t => t.id === track.id);
                }
                document.dispatchEvent(new Event('queue-updated'));

                // After everything is set up, preload the next track
                setTimeout(preloadNextTrack, 5000); // Wait 5 seconds before preloading
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
                let imgSrc = track.album_art_url;
                
                // If it's an external URL, route through proxy
                if (imgSrc.startsWith('http')) {
                    imgSrc = `/albumart/${encodeURIComponent(imgSrc)}`;
                }
                // If it's a cache path, use directly
                
                nowPlayingArt.src = imgSrc;
                nowPlayingArt.onerror = function() {
                    this.src = '/static/images/default-album-art.png';
                };
            } else {
                nowPlayingArt.src = '/static/images/default-album-art.png';
            }
        }
        
        // Update document title
        document.title = `${track.title} - ${track.artist} | PUMP`;

        // Set current track ID for the like button
        currentTrackId = track.id;
        
        // Check like status and update button
        fetch(`/api/tracks/${track.id}/liked`)
            .then(response => response.json())
            .then(data => {
                updateLikeButton(data.liked);
            })
            .catch(error => {
                console.error('Error checking like status:', error);
            });

        // Update Media Session API if available
        if ('mediaSession' in navigator) {
            navigator.mediaSession.metadata = new MediaMetadata({
                title: track.title || 'Unknown Title',
                artist: track.artist || 'Unknown Artist',
                album: track.album || 'Unknown Album',
                artwork: [
                    { src: track.album_art_url || '/static/images/default-album-art.png', sizes: '512x512', type: 'image/png' }
                ]
            });
            
            // Set action handlers
            navigator.mediaSession.setActionHandler('play', () => {
                audioPlayer.play();
                isPlaying = true;
                updatePlayPauseButton();
            });
            
            navigator.mediaSession.setActionHandler('pause', () => {
                audioPlayer.pause();
                isPlaying = false;
                updatePlayPauseButton();
            });
            
            navigator.mediaSession.setActionHandler('previoustrack', playPreviousTrack);
            navigator.mediaSession.setActionHandler('nexttrack', playNextTrack);
        }
    }
    
    function togglePlayPause() {
        console.log('togglePlayPause called, audioPlayer exists:', !!audioPlayer);
        
        if (!audioPlayer) return;
        
        if (audioPlayer.paused) {
            console.log('Audio was paused, attempting to play');
            audioPlayer.play()
                .then(() => {
                    isPlaying = true;
                    updatePlayPauseButton();
                })
                .catch(error => {
                    console.error('Play prevented:', error);
                });
        } else {
            console.log('Audio was playing, pausing');
            audioPlayer.pause();
            isPlaying = false;
            updatePlayPauseButton();
        }
    }
    
    function updatePlayPauseButton() {
        if (!playPauseButton) return;
        
        console.log('Updating play/pause button, isPlaying:', isPlaying);
        
        if (isPlaying) {
            playPauseButton.textContent = '⏸'; // Pause symbol
            playPauseButton.title = 'Pause';
        } else {
            playPauseButton.textContent = '▶'; // Play symbol
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
            // Ensure percent is between 0 and 1
            percent = Math.max(0, Math.min(1, percent));
            audioPlayer.currentTime = percent * duration;
            
            // Update the visual progress immediately
            if (progressFill) {
                progressFill.style.width = `${percent * 100}%`;
            }
            
            // Update the current time display
            if (currentTimeDisplay) {
                currentTimeDisplay.textContent = formatTime(percent * duration);
            }
            
            // Log the seek operation for debugging
            console.log(`Seeking to ${percent * 100}% (${formatTime(percent * duration)})`);
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

    // Like button functionality
    let currentTrackId = null;

    if (likeButton) {
        likeButton.addEventListener('click', function() {
            if (currentTrackId) {
                toggleLikeStatus(currentTrackId);
            }
        });
    }

    // Add these functions to handle like status

    function toggleLikeStatus(trackId) {
        fetch(`/api/tracks/${trackId}/like`, {
            method: 'POST'
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                console.error('Error toggling like status:', data.error);
                return;
            }
            
            updateLikeButton(data.liked);
            
            // Update any other instances of this track in the UI
            document.querySelectorAll(`.track-like-button[data-id="${trackId}"]`).forEach(btn => {
                if (data.liked) {
                    btn.classList.add('liked');
                    btn.innerHTML = '♥';
                    btn.title = 'Unlike';
                } else {
                    btn.classList.remove('liked');
                    btn.innerHTML = '♡';
                    btn.title = 'Like';
                }
            });
        })
        .catch(error => {
            console.error('Error toggling like status:', error);
        });
    }

    function updateLikeButton(isLiked) {
        if (!likeButton) return;
        
        if (isLiked) {
            likeButton.classList.add('liked');
            likeButton.innerHTML = '♥';
            likeButton.title = 'Unlike';
        } else {
            likeButton.classList.remove('liked');
            likeButton.innerHTML = '♡';
            likeButton.title = 'Like';
        }
    }

    // Save playback state before page unload
    window.addEventListener('beforeunload', function() {
        // Only save if we're actually playing something
        if (audioPlayer && audioPlayer.src && !audioPlayer.paused) {
            const playbackState = {
                trackId: currentTrackId,
                currentTime: audioPlayer.currentTime,
                isPlaying: !audioPlayer.paused,
                queue: queue,
                currentTrackIndex: currentTrackIndex,
                timestamp: Date.now()
            };
            localStorage.setItem('playbackState', JSON.stringify(playbackState));
        }
    });

    // Add this after your other initialization code
    function restorePlaybackState() {
        try {
            const savedState = localStorage.getItem('playbackState');
            if (!savedState) return false;
            
            const state = JSON.parse(savedState);
            
            // Only restore if saved less than 1 hour ago
            if (Date.now() - state.timestamp > 3600000) {
                localStorage.removeItem('playbackState');
                return false;
            }
            
            console.log('Restoring playback state:', state);
            
            // Restore queue
            if (Array.isArray(state.queue) && state.queue.length > 0) {
                queue = state.queue;
                currentTrackIndex = state.currentTrackIndex || 0;
            }
            
            // Restore current track
            if (state.trackId) {
                // Set high priority for audio loading
                const audioPlayer = document.getElementById('audio-player');
                if (audioPlayer) {
                    audioPlayer.preload = 'auto';
                    audioPlayer.setAttribute('data-prioritize', 'true');
                }
                
                // Play the track but don't autoplay yet
                const autoplay = state.isPlaying;
                playTrackById(state.trackId, autoplay, state.currentTime);
                
                // For autoplay, focus on getting audio going quickly
                if (autoplay) {
                    // Add a class to body to indicate we're restoring playback
                    document.body.classList.add('restoring-playback');
                    
                    // Remove the class after restoration is complete
                    setTimeout(() => {
                        document.body.classList.remove('restoring-playback');
                    }, 2000);
                }
                
                return true;
            }
        } catch (e) {
            console.error('Error restoring playback state:', e);
        }
        return false;
    }

    // Call this at the end of the DOMContentLoaded event
    setTimeout(restorePlaybackState, 500); // Small delay to ensure all UI is ready

    // Add these optimizations to help with smoother transitions

    // After your playTrackById function, add this function to preload the next track
    function preloadNextTrack() {
        if (queue.length === 0 || currentTrackIndex >= queue.length - 1) return;
        
        const nextTrack = queue[currentTrackIndex + 1];
        if (!nextTrack || !nextTrack.id) return;
        
        // Create a hidden audio element to preload the next track
        const preloader = document.createElement('audio');
        preloader.style.display = 'none';
        preloader.preload = 'auto';
        preloader.src = `/stream/${nextTrack.id}`;
        
        // Remove preloader once it's loaded enough data
        preloader.addEventListener('canplaythrough', function() {
            document.body.removeChild(preloader);
        });
        
        // Add to DOM to start loading
        document.body.appendChild(preloader);
        
        console.log(`Preloading next track: ${nextTrack.title}`);
    }

    // Handle play button when no track is playing
    if (playPauseButton) {
        playPauseButton.addEventListener('click', function() {
            if (!audioPlayer.src) {
                // If nothing is playing, try to load a previous track or recent track
                restorePlaybackState() || loadRecentTrack();
            } else {
                togglePlayPause();
            }
        });
    }
});

// Add this function at the bottom
function loadRecentTrack() {
    // Fetch a recent track to play
    fetch('/recent?limit=1')
        .then(response => response.json())
        .then(data => {
            if (Array.isArray(data) && data.length > 0) {
                playTrackById(data[0].id);
                return true;
            }
            return false;
        })
        .catch(error => {
            console.error('Error loading recent track:', error);
            return false;
        });
}

// Add or verify this code in your player-controls.js file:

document.addEventListener('DOMContentLoaded', function() {
    // DOM elements
    const audioPlayer = document.getElementById('audio-player');
    const playPauseButton = document.getElementById('play-pause');
    
    // Debug logging
    console.log('Audio player element:', audioPlayer);
    console.log('Play/pause button element:', playPauseButton);
    
    // Attach event listener to play/pause button
    if (playPauseButton) {
        console.log('Adding click event to play/pause button');
        playPauseButton.addEventListener('click', function() {
            console.log('Play/Pause button clicked');
            togglePlayPause();
        });
    } else {
        console.error('Play/pause button not found in the DOM');
    }
    
    // Toggle play/pause function
    function togglePlayPause() {
        console.log('Toggle play/pause called');
        console.log('Audio player paused state before toggle:', audioPlayer.paused);
        
        if (audioPlayer.paused) {
            audioPlayer.play().then(() => {
                console.log('Started playback');
                playPauseButton.textContent = '⏸';
            }).catch(error => {
                console.error('Error starting playback:', error);
            });
        } else {
            audioPlayer.pause();
            console.log('Paused playback');
            playPauseButton.textContent = '▶';
        }
    }
    
    // Make togglePlayPause available globally
    window.togglePlayPause = togglePlayPause;
});

// Check if this is happening somewhere in your code
function loadTrack(trackId) {
    fetch(`/api/tracks/${trackId}`)
        .then(response => response.json())
        .then(track => {
            const audioPlayer = document.getElementById('audio-player');
            audioPlayer.src = track.file_url;
            audioPlayer.load(); // Important for some browsers
            
            // Update UI elements
            document.getElementById('now-playing-title').textContent = track.title;
            document.getElementById('now-playing-artist').textContent = track.artist;
            
            // After loading, you can play
            audioPlayer.play().then(() => {
                document.getElementById('play-pause').textContent = '⏸';
            });
        });
}