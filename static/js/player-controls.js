// Player controls functionality

document.addEventListener('DOMContentLoaded', function() {
    console.log('Initializing player-controls.js');
    
    // Get DOM elements
    const audioPlayer = document.getElementById('audio-player');
    const playPauseBtn = document.getElementById('play-pause');
    const prevBtn = document.getElementById('prev-track');
    const nextBtn = document.getElementById('next-track');
    const progressBar = document.querySelector('.progress-bar');
    const progressFill = document.getElementById('progress-fill');
    const currentTimeDisplay = document.getElementById('current-time');
    const totalTimeDisplay = document.getElementById('total-time');
    const volumeSlider = document.getElementById('volume-slider');
    const muteButton = document.getElementById('mute-button');
    const likeButton = document.getElementById('like-track');
    
    // Check if playerManager exists
    if (!window.playerManager) {
        console.error('PlayerManager not found. Audio controls may not work properly.');
        return;
    }
    
    // Progress bar click handling
    if (progressBar) {
        progressBar.addEventListener('click', function(e) {
            if (!audioPlayer || !audioPlayer.duration) return;
            
            const rect = this.getBoundingClientRect();
            const pos = (e.clientX - rect.left) / rect.width;
            audioPlayer.currentTime = pos * audioPlayer.duration;
        });
        
        // Make progress bar draggable
        let isDragging = false;
        
        progressBar.addEventListener('mousedown', function() {
            isDragging = true;
            progressBar.classList.add('dragging');
        });
        
        document.addEventListener('mousemove', function(e) {
            if (!isDragging || !audioPlayer || !audioPlayer.duration) return;
            
            const rect = progressBar.getBoundingClientRect();
            let pos = (e.clientX - rect.left) / rect.width;
            pos = Math.max(0, Math.min(1, pos)); // Clamp between 0 and 1
            
            // Update UI while dragging
            progressFill.style.width = `${pos * 100}%`;
            
            // Calculate and display time
            const time = pos * audioPlayer.duration;
            currentTimeDisplay.textContent = formatTime(time);
        });
        
        document.addEventListener('mouseup', function(e) {
            if (!isDragging) return;
            
            const rect = progressBar.getBoundingClientRect();
            let pos = (e.clientX - rect.left) / rect.width;
            pos = Math.max(0, Math.min(1, pos)); // Clamp between 0 and 1
            
            // Set the time when finished dragging
            if (audioPlayer && audioPlayer.duration) {
                audioPlayer.currentTime = pos * audioPlayer.duration;
            }
            
            isDragging = false;
            progressBar.classList.remove('dragging');
        });
    }
    
    // Volume control
    if (volumeSlider) {
        volumeSlider.addEventListener('input', function() {
            if (!audioPlayer) return;
            
            const volume = parseFloat(this.value);
            audioPlayer.volume = volume;
            
            // Save volume preference
            localStorage.setItem('volume', volume);
            
            // Update mute button icon
            updateMuteButtonIcon(volume);
        });
        
        // Load saved volume
        const savedVolume = localStorage.getItem('volume');
        if (savedVolume !== null) {
            const volume = parseFloat(savedVolume);
            volumeSlider.value = volume;
            if (audioPlayer) audioPlayer.volume = volume;
            updateMuteButtonIcon(volume);
        }
    }
    
    // Mute button
    if (muteButton) {
        muteButton.addEventListener('click', function() {
            if (!audioPlayer) return;
            
            if (audioPlayer.volume > 0) {
                // Store current volume and mute
                localStorage.setItem('volumeBeforeMute', audioPlayer.volume);
                audioPlayer.volume = 0;
                volumeSlider.value = 0;
                updateMuteButtonIcon(0);
            } else {
                // Restore previous volume
                const previousVolume = parseFloat(localStorage.getItem('volumeBeforeMute') || 0.7);
                audioPlayer.volume = previousVolume;
                volumeSlider.value = previousVolume;
                updateMuteButtonIcon(previousVolume);
            }
        });
    }
    
    // Handle like button
    if (likeButton) {
        likeButton.addEventListener('click', function() {
            // Get the currently playing track ID
            const trackId = window.playerManager.currentTrackId;
            if (!trackId) {
                console.log('No track currently playing');
                return;
            }
            
            const isCurrentlyLiked = likeButton.classList.contains('liked');
            const action = isCurrentlyLiked ? 'unlike' : 'like';
            
            fetch(`/api/tracks/${trackId}/${action}`, {
                method: 'POST'
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    // Toggle liked state visually
                    likeButton.classList.toggle('liked');
                    likeButton.textContent = isCurrentlyLiked ? '♡' : '♥';
                    
                    // Show feedback
                    const message = isCurrentlyLiked ? 'Removed from liked tracks' : 'Added to liked tracks';
                    showToast(message);
                } else {
                    console.error('Error toggling like:', data.error);
                }
            })
            .catch(error => {
                console.error('Error toggling like:', error);
            });
        });
    }
    
    // Helper function to update mute button icon
    function updateMuteButtonIcon(volume) {
        if (!muteButton) return;
        
        if (volume === 0) {
            muteButton.textContent = '🔇';
        } else if (volume < 0.5) {
            muteButton.textContent = '🔉';
        } else {
            muteButton.textContent = '🔊';
        }
    }
    
    // Helper function to format time
    function formatTime(time) {
        if (isNaN(time)) return '0:00';
        
        const minutes = Math.floor(time / 60);
        const seconds = Math.floor(time % 60).toString().padStart(2, '0');
        return `${minutes}:${seconds}`;
    }
    
    // Show toast notification
    function showToast(message) {
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
        
        // Remove toast after 3 seconds
        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => {
                toast.remove();
            }, 500);
        }, 3000);
    }
});

// Add this function at the bottom
function loadRecentTrack() {
    // This functionality is now handled by the PlayerManager
    if (window.playerManager) {
        window.playerManager.loadRecentTrack();
    }
}