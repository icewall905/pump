/**
 * PlayerManager - Handles audio playback, track history, and queue management
 * Replaces the previous SQLite memory database approach with a client-side system
 */
class PlayerManager {
    constructor() {
        console.log('Initializing PlayerManager');
        this.audioPlayer = document.getElementById('audio-player');
        this.nowPlayingBar = document.getElementById('now-playing-bar');
        this.playPauseBtn = document.getElementById('play-pause');
        this.prevTrackBtn = document.getElementById('prev-track');
        this.nextTrackBtn = document.getElementById('next-track');
        this.progressFill = document.getElementById('progress-fill');
        this.currentTimeDisplay = document.getElementById('current-time');
        this.totalTimeDisplay = document.getElementById('total-time');
        this.nowPlayingTitle = document.getElementById('now-playing-title');
        this.nowPlayingArtist = document.getElementById('now-playing-artist');
        this.nowPlayingArt = document.getElementById('now-playing-art');
        this.likeButton = document.getElementById('like-track');
        
        // Track management
        this.queue = [];          // Upcoming tracks
        this.history = [];        // Previously played tracks
        this.currentTrack = null; // Currently playing track
        this.currentTrackId = null; // ID of current track
        
        // Initialize event listeners
        this.initializeEventListeners();
        
        // Load recent track from local storage
        this.loadRecentTrack();
    }
    
    initializeEventListeners() {
        if (!this.audioPlayer) {
            console.error('Audio player element not found!');
            return;
        }
        
        // Audio player events
        this.audioPlayer.addEventListener('timeupdate', () => this.updateProgressBar());
        this.audioPlayer.addEventListener('ended', () => this.playNextTrack());
        this.audioPlayer.addEventListener('play', () => this.updatePlayPauseButton(true));
        this.audioPlayer.addEventListener('pause', () => this.updatePlayPauseButton(false));
        
        // Control button events
        if (this.playPauseBtn) {
            this.playPauseBtn.addEventListener('click', () => this.togglePlayPause());
        }
        
        if (this.nextTrackBtn) {
            this.nextTrackBtn.addEventListener('click', () => this.playNextTrack());
        }
        
        if (this.prevTrackBtn) {
            this.prevTrackBtn.addEventListener('click', () => this.playPreviousTrack());
        }
    }
    
    // Play a specific track by ID
    playTrack(trackId) {
        console.log(`Playing track: ${trackId}`);
        
        // Clear any existing audio source first to prevent AbortError
        if (this.audioPlayer) {
            this.audioPlayer.pause();
            this.audioPlayer.removeAttribute('src');
            this.audioPlayer.load();
        }
        
        // Fetch track details and URL from the API
        fetch(`/api/tracks/${trackId}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Failed to fetch track: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.error) {
                    console.error('Error fetching track:', data.error);
                    return;
                }
                
                // If we're playing a different track, add the current one to history
                if (this.currentTrackId && this.currentTrackId !== trackId) {
                    this.history.push(this.currentTrack);
                    // Keep history at a reasonable size
                    if (this.history.length > 50) {
                        this.history.shift();
                    }
                }
                
                // Update current track
                this.currentTrack = data;
                this.currentTrackId = trackId;
                
                // FIXED: Use the correct streaming endpoint format based on API
                // Try the ID-based endpoint first, and if file_path exists, use that as fallback
                let streamUrl;
                if (data.file_path) {
                    // Use file path-based streaming if available
                    streamUrl = `/api/stream?path=${encodeURIComponent(data.file_path)}`;
                } else {
                    // Otherwise use ID-based streaming
                    streamUrl = `/stream/${trackId}`;
                }
                
                console.log(`Using stream URL: ${streamUrl}`);
                
                // Set audio source and play
                this.audioPlayer.src = streamUrl;
                
                // Play after a small delay to prevent AbortError
                setTimeout(() => {
                    this.audioPlayer.play().catch(err => {
                        console.error('Error playing track:', err);
                    });
                }, 50);
                
                // Update the UI
                this.updateNowPlayingUI(data);
                
                // Save to local storage
                localStorage.setItem('lastTrackId', trackId);
                
                // Check if track is liked (with error handling)
                this.checkTrackLikeStatus(trackId);
            })
            .catch(error => {
                console.error('Error playing track:', error);
                this.showToast('Error playing track: ' + error.message);
            });
    }
    
    // Update the progress bar based on current playback time
    updateProgressBar() {
        if (!this.audioPlayer || !this.progressFill) return;
        
        if (this.audioPlayer.duration) {
            const percent = (this.audioPlayer.currentTime / this.audioPlayer.duration) * 100;
            this.progressFill.style.width = `${percent}%`;
            
            // Update time displays
            if (this.currentTimeDisplay) {
                this.currentTimeDisplay.textContent = this.formatTime(this.audioPlayer.currentTime);
            }
            
            if (this.totalTimeDisplay) {
                this.totalTimeDisplay.textContent = this.formatTime(this.audioPlayer.duration);
            }
        }
    }
    
    // Format time in seconds to MM:SS format
    formatTime(time) {
        if (isNaN(time)) return '0:00';
        
        const minutes = Math.floor(time / 60);
        const seconds = Math.floor(time % 60).toString().padStart(2, '0');
        return `${minutes}:${seconds}`;
    }
    
    // Toggle play/pause
    togglePlayPause() {
        if (!this.audioPlayer) return;
        
        if (this.audioPlayer.paused) {
            if (this.audioPlayer.src) {
                this.audioPlayer.play().catch(err => {
                    console.error('Error playing audio:', err);
                });
            } else if (this.currentTrackId) {
                // If we have a track ID but no source, reload it
                this.playTrack(this.currentTrackId);
            }
        } else {
            this.audioPlayer.pause();
        }
    }
    
    // Update the play/pause button appearance
    updatePlayPauseButton(isPlaying) {
        if (!this.playPauseBtn) return;
        
        if (isPlaying) {
            this.playPauseBtn.textContent = '⏸';
            this.playPauseBtn.title = 'Pause';
            this.nowPlayingBar.classList.add('active');
            this.nowPlayingBar.classList.remove('empty');
        } else {
            this.playPauseBtn.textContent = '▶';
            this.playPauseBtn.title = 'Play';
            if (!this.currentTrack) {
                this.nowPlayingBar.classList.add('empty');
            }
        }
    }
    
    // Update the Now Playing bar with current track info
    updateNowPlayingUI(track) {
        if (!track) return;
        
        if (this.nowPlayingTitle) {
            this.nowPlayingTitle.textContent = track.title || 'Unknown Title';
        }
        
        if (this.nowPlayingArtist) {
            this.nowPlayingArtist.textContent = track.artist || 'Unknown Artist';
        }
        
        if (this.nowPlayingArt) {
            if (track.albumArtUrl) {
                this.nowPlayingArt.src = track.albumArtUrl;
            } else {
                // Default album art
                this.nowPlayingArt.src = '/static/images/default-album-art.png';
            }
        }
    }
    
    // Play the next track in the queue
    playNextTrack() {
        if (this.queue.length > 0) {
            // Get next track from queue
            const nextTrack = this.queue.shift();
            this.playTrack(nextTrack.id);
        } else {
            // No more tracks in queue
            console.log('End of queue reached');
        }
    }
    
    // Play the previous track from history
    playPreviousTrack() {
        if (this.history.length > 0) {
            // Get the most recent track from history
            const prevTrack = this.history.pop();
            
            // Add current track to the front of the queue
            if (this.currentTrack) {
                this.queue.unshift(this.currentTrack);
            }
            
            // Play the previous track
            this.playTrack(prevTrack.id);
        } else {
            // No history, restart current track
            if (this.audioPlayer) {
                this.audioPlayer.currentTime = 0;
            }
        }
    }
    
    // Add a track to the queue
    addToQueue(track) {
        this.queue.push(track);
        
        // If nothing is playing, start playing the first track in the queue
        if (!this.currentTrack || this.audioPlayer.paused) {
            this.playNextTrack();
        }
        
        // Show notification
        this.showToast(`Added "${track.title}" to queue`);
    }
    
    // Add multiple tracks to the queue
    addMultipleToQueue(tracks) {
        if (!tracks || tracks.length === 0) return;
        
        this.queue.push(...tracks);
        
        // If nothing is playing, start playing the first track in the queue
        if (!this.currentTrack || this.audioPlayer.paused) {
            this.playNextTrack();
        }
        
        this.showToast(`Added ${tracks.length} tracks to queue`);
    }
    
    // Clear the queue
    clearQueue() {
        this.queue = [];
        this.showToast('Queue cleared');
    }
    
    // Get the current queue
    getQueue() {
        return this.queue;
    }
    
    // Show a toast notification
    showToast(message) {
        // Check if toast container exists, create if not
        let toastContainer = document.querySelector('.toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.className = 'toast-container';
            document.body.appendChild(toastContainer);
        }
        
        // Create toast
        const toast = document.createElement('div');
        toast.className = 'toast-notification';
        toast.textContent = message;
        toastContainer.appendChild(toast);
        
        // Remove after 3 seconds
        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => {
                toast.remove();
            }, 500);
        }, 3000);
    }
    
    // Check if the current track is liked
    checkTrackLikeStatus(trackId) {
        if (!this.likeButton) return;
        
        // First, set a default state to avoid incorrect UI
        this.likeButton.classList.remove('liked');
        this.likeButton.textContent = '♡';
        
        fetch(`/api/tracks/${trackId}/liked`)
            .then(response => {
                // Check if response is OK before trying to parse JSON
                if (!response.ok) {
                    // If endpoint doesn't exist, quietly fail without error in console
                    if (response.status === 404) {
                        console.log('Like status endpoint not available (404), skipping like status check');
                        return null;
                    }
                    throw new Error(`Server returned ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                // Skip processing if we returned null (404 case)
                if (data === null) return;
                
                if (data.liked) {
                    this.likeButton.classList.add('liked');
                    this.likeButton.textContent = '♥';
                } else {
                    this.likeButton.classList.remove('liked');
                    this.likeButton.textContent = '♡';
                }
            })
            .catch(error => {
                // Only log detailed error if not a 404
                console.error('Error checking like status:', error);
            });
    }
    
    // Load most recently played track from local storage
    loadRecentTrack() {
        const lastTrackId = localStorage.getItem('lastTrackId');
        if (lastTrackId) {
            // Verify track exists before loading it
            fetch(`/api/tracks/${lastTrackId}`)
                .then(response => response.json())
                .then(data => {
                    if (!data.error) {
                        // Don't autoplay, just set up the UI
                        this.currentTrack = data;
                        this.currentTrackId = lastTrackId;
                        this.updateNowPlayingUI(data);
                        this.checkTrackLikeStatus(lastTrackId);
                    }
                })
                .catch(error => {
                    console.error('Error loading recent track:', error);
                });
        }
    }
}

// Create a namespace for PlayerManager initialization
window.PUMPPlayer = {
    isReady: false,
    pendingCallbacks: [],
    manager: null,
    
    // Function to initialize the PlayerManager
    initialize: function() {
        console.log('PlayerManager initialization started');
        
        if (this.manager) {
            console.log('PlayerManager already initialized');
            return this.manager;
        }
        
        try {
            // Create PlayerManager instance
            this.manager = new PlayerManager();
            window.playerManager = this.manager; // Also set global reference
            
            // Create global playTrack function that all components can use
            window.playTrack = function(trackId) {
                console.log('Global playTrack called with ID:', trackId);
                if (window.playerManager) {
                    window.playerManager.playTrack(trackId);
                } else {
                    console.error('PlayerManager not available for playTrack function');
                    // Store the track ID for later playback
                    window.pendingPlayTrackId = trackId;
                }
            };
            
            // Set ready state and process queued callbacks
            this.isReady = true;
            this.processPendingCallbacks();
            
            // Handle any pending track playback
            if (window.pendingPlayTrackId) {
                console.log('Playing pending track:', window.pendingPlayTrackId);
                window.playTrack(window.pendingPlayTrackId);
                window.pendingPlayTrackId = null;
            }
            
            console.log('PlayerManager successfully initialized');
            return this.manager;
        } catch (error) {
            console.error('Error initializing PlayerManager:', error);
            this.isReady = false;
            return null;
        }
    },
    
    // Function to add callback to be executed when PlayerManager is ready
    ready: function(callback) {
        if (this.isReady && this.manager) {
            // If already ready, execute immediately
            callback(this.manager);
        } else {
            // Otherwise queue for execution
            this.pendingCallbacks.push(callback);
        }
    },
    
    // Process all pending callbacks
    processPendingCallbacks: function() {
        console.log(`Processing ${this.pendingCallbacks.length} pending callbacks`);
        
        while (this.pendingCallbacks.length > 0) {
            const callback = this.pendingCallbacks.shift();
            try {
                callback(this.manager);
            } catch (error) {
                console.error('Error executing callback:', error);
            }
        }
    }
};

// Initialize the player manager when the DOM is fully loaded
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM loaded - initializing PlayerManager');
    window.PUMPPlayer.initialize();
    
    // Dispatch a custom event that other scripts can listen for
    document.dispatchEvent(new CustomEvent('playerManagerReady'));
    
    // Also execute any remaining inline scripts (this is a safety measure)
    setTimeout(function() {
        if (typeof window.onPlayerManagerReady === 'function') {
            window.onPlayerManagerReady(window.playerManager);
        }
    }, 100);
});