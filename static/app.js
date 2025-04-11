// PUMP Music Player - Main Application JavaScript

document.addEventListener('DOMContentLoaded', function() {
    console.log('PUMP Music Player application initialized');

    // Create and initialize the main player manager
    window.playerManager = new PlayerManager();

    // Initialize page-specific functionality based on the current page
    initializeCurrentPage();
});

/**
 * Player Manager - Handles all audio playback functionality
 */
class PlayerManager {
    constructor() {
        this.audioPlayer = document.getElementById('audio-player');
        this.nowPlayingBar = document.getElementById('now-playing-bar');
        this.nowPlayingArt = document.getElementById('now-playing-art');
        this.nowPlayingTitle = document.getElementById('now-playing-title');
        this.nowPlayingArtist = document.getElementById('now-playing-artist');
        this.playPauseButton = document.getElementById('play-pause');
        this.progressFill = document.getElementById('progress-fill');
        this.currentTimeDisplay = document.getElementById('current-time');
        this.totalTimeDisplay = document.getElementById('total-time');
        this.prevButton = document.getElementById('prev-track');
        this.nextButton = document.getElementById('next-track');
        
        // Queue management
        this.queue = [];
        this.history = [];
        this.currentTrackIndex = -1;
        this.currentTrackId = null;
        this.isPlaying = false;

        // Initialize
        this.initialize();
    }

    initialize() {
        console.log('Initializing player manager');
        
        // Set up event listeners
        if (this.audioPlayer) {
            this.audioPlayer.addEventListener('ended', () => this.onTrackEnded());
            this.audioPlayer.addEventListener('timeupdate', () => this.updateProgress());
            this.audioPlayer.addEventListener('play', () => this.onPlay());
            this.audioPlayer.addEventListener('pause', () => this.onPause());
            this.audioPlayer.addEventListener('error', (e) => this.onError(e));
            
            // Set initial volume
            this.audioPlayer.volume = 0.7;
        } else {
            console.error('Audio player element not found');
        }
        
        // Set up control button listeners
        if (this.playPauseButton) {
            this.playPauseButton.addEventListener('click', () => this.togglePlayPause());
        }
        
        if (this.prevButton) {
            this.prevButton.addEventListener('click', () => this.playPrevious());
        }
        
        if (this.nextButton) {
            this.nextButton.addEventListener('click', () => this.playNext());
        }
        
        // Try to load most recent track if available
        this.loadRecentTrack();
    }
    
    /**
     * Play a specific track by file path
     * @param {string} filePath - Path to the audio file
     * @param {boolean} resetQueue - Whether to reset the queue or add to it
     */
    playTrack(filePath, resetQueue = true) {
        console.log(`Playing track: ${filePath}`);
        
        if (!filePath) {
            console.error('No file path provided');
            return;
        }
        
        // If this is a new session, reset the queue
        if (resetQueue || this.queue.length === 0) {
            this.queue = [filePath];
            this.currentTrackIndex = 0;
        } else {
            // Add to queue and play immediately
            this.queue.push(filePath);
            this.currentTrackIndex = this.queue.length - 1;
        }
        
        // Get track metadata
        fetch(`/api/tracks/info?path=${encodeURIComponent(filePath)}`)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    console.error('Error fetching track info:', data.error);
                    return;
                }
                
                // Update player UI
                this.updateNowPlayingDisplay(data);
                
                // Save track ID for later
                this.currentTrackId = data.id || null;
                
                // Add track to recent history if it has an ID
                if (data.id) {
                    this.addToHistory(data.id);
                }
                
                // Play the audio
                this.audioPlayer.src = `/api/stream?path=${encodeURIComponent(filePath)}`;
                this.audioPlayer.play()
                    .catch(error => console.error('Error playing audio:', error));
                
                // Show now playing bar
                if (this.nowPlayingBar) {
                    this.nowPlayingBar.classList.add('active');
                    this.nowPlayingBar.classList.remove('empty');
                }
                
                // Update play button state
                if (this.playPauseButton) {
                    this.playPauseButton.textContent = '❚❚';
                }
                
                // Update isPlaying state
                this.isPlaying = true;
            })
            .catch(error => {
                console.error('Error:', error);
                
                // Fallback to play without metadata
                this.audioPlayer.src = `/api/stream?path=${encodeURIComponent(filePath)}`;
                this.audioPlayer.play()
                    .catch(err => console.error('Error playing audio:', err));
            });
    }
    
    /**
     * Play a specific track by ID
     * @param {number} trackId - ID of the track to play
     */
    playTrackById(trackId) {
        console.log(`Global playTrack called with ID: ${trackId}`);

        // Update the stream URL to use the correct endpoint
        const streamUrl = `/stream/${trackId}`;
        console.log(`Using stream URL: ${streamUrl}`);

        // Set the audio source and play
        this.audioPlayer.src = streamUrl;
        this.audioPlayer.play().catch(error => {
            console.error('Error playing track:', error);
        });

        // Check like status using the correct endpoint
        this.checkTrackLikeStatus(trackId);
    }
    
    /**
     * Toggle between play and pause
     */
    togglePlayPause() {
        if (!this.audioPlayer) return;
        
        if (this.audioPlayer.paused) {
            if (this.audioPlayer.src) {
                this.audioPlayer.play();
            } else if (this.queue.length > 0 && this.currentTrackIndex >= 0) {
                this.playTrack(this.queue[this.currentTrackIndex], false);
            } else {
                this.loadRecentTrack();
            }
        } else {
            this.audioPlayer.pause();
        }
    }
    
    /**
     * Play the next track in the queue
     */
    playNext() {
        if (this.queue.length === 0) {
            console.log('Queue is empty');
            return;
        }
        
        if (this.currentTrackIndex < this.queue.length - 1) {
            this.currentTrackIndex++;
            this.playTrack(this.queue[this.currentTrackIndex], false);
        } else {
            console.log('Reached end of queue');
            // Optional: loop back to beginning
            // this.currentTrackIndex = 0;
            // this.playTrack(this.queue[this.currentTrackIndex], false);
        }
    }
    
    /**
     * Play the previous track in the queue
     */
    playPrevious() {
        if (this.queue.length === 0) {
            console.log('Queue is empty');
            return;
        }
        
        // If we're more than 3 seconds into the track, restart it instead of going back
        if (this.audioPlayer.currentTime > 3) {
            this.audioPlayer.currentTime = 0;
            return;
        }
        
        if (this.currentTrackIndex > 0) {
            this.currentTrackIndex--;
            this.playTrack(this.queue[this.currentTrackIndex], false);
        } else {
            console.log('Already at beginning of queue');
            // Optional: loop to end
            // this.currentTrackIndex = this.queue.length - 1;
            // this.playTrack(this.queue[this.currentTrackIndex], false);
            
            // Or just restart current track
            this.audioPlayer.currentTime = 0;
        }
    }
    
    /**
     * Update the progress bar and time displays
     */
    updateProgress() {
        if (!this.audioPlayer || !this.progressFill || !this.currentTimeDisplay || !this.totalTimeDisplay) return;
        
        const currentTime = this.audioPlayer.currentTime;
        const duration = this.audioPlayer.duration;
        
        if (duration > 0) {
            // Update progress bar
            const progressPercent = (currentTime / duration) * 100;
            this.progressFill.style.width = `${progressPercent}%`;
            
            // Update time displays
            this.currentTimeDisplay.textContent = this.formatTime(currentTime);
            this.totalTimeDisplay.textContent = this.formatTime(duration);
        }
    }
    
    /**
     * Format seconds into MM:SS display
     * @param {number} time - Time in seconds
     * @returns {string} Formatted time
     */
    formatTime(time) {
        if (isNaN(time)) return '0:00';
        
        const minutes = Math.floor(time / 60);
        const seconds = Math.floor(time % 60).toString().padStart(2, '0');
        return `${minutes}:${seconds}`;
    }
    
    /**
     * Update now playing display with track metadata
     * @param {object} trackData - Track metadata
     */
    updateNowPlayingDisplay(trackData) {
        if (!this.nowPlayingTitle || !this.nowPlayingArtist || !this.nowPlayingArt) return;
        
        // Update track info
        this.nowPlayingTitle.textContent = trackData.title || 'Unknown Track';
        this.nowPlayingArtist.textContent = trackData.artist || 'Unknown Artist';
        
        // Update album art if available
        if (trackData.album_art_url) {
            this.nowPlayingArt.src = trackData.album_art_url;
        } else {
            this.nowPlayingArt.src = '/static/images/default-album-art.png';
        }
    }
    
    /**
     * Handle track ended event
     */
    onTrackEnded() {
        this.playNext();
    }
    
    /**
     * Handle audio play event
     */
    onPlay() {
        if (this.playPauseButton) {
            this.playPauseButton.textContent = '❚❚';
        }
        this.isPlaying = true;
    }
    
    /**
     * Handle audio pause event
     */
    onPause() {
        if (this.playPauseButton) {
            this.playPauseButton.textContent = '▶';
        }
        this.isPlaying = false;
    }
    
    /**
     * Handle audio error event
     */
    onError(error) {
        console.error('Audio player error:', error);
        if (this.nowPlayingTitle) {
            this.nowPlayingTitle.textContent = 'Error playing track';
        }
        if (this.nowPlayingArtist) {
            this.nowPlayingArtist.textContent = 'Please try another track';
        }
    }
    
    /**
     * Add a track to play history
     * @param {number|string} trackId - Track ID
     */
    addToHistory(trackId) {
        // Don't add if it's already the most recent in history
        if (this.history.length > 0 && this.history[this.history.length - 1] === trackId) {
            return;
        }
        
        this.history.push(trackId);
        
        // Keep history at a reasonable size
        if (this.history.length > 100) {
            this.history.shift();
        }
        
        // Save to localStorage
        localStorage.setItem('recentTrackId', trackId);
    }
    
    /**
     * Load the most recently played track
     */
    loadRecentTrack() {
        const recentId = localStorage.getItem('recentTrackId');
        if (recentId) {
            fetch(`/api/tracks/${recentId}`)
                .then(response => response.json())
                .then(data => {
                    if (data && data.file_path) {
                        console.log('Loading recent track:', data.title);
                        
                        // Add to queue without playing
                        this.queue = [data.file_path];
                        this.currentTrackIndex = 0;
                        
                        // Update now playing display
                        this.updateNowPlayingDisplay(data);
                        
                        // Show now playing bar but don't play automatically
                        if (this.nowPlayingBar) {
                            this.nowPlayingBar.classList.add('active');
                            this.nowPlayingBar.classList.remove('empty');
                        }
                        
                        // Save current track ID
                        this.currentTrackId = data.id;
                    }
                })
                .catch(error => {
                    console.error('Error loading recent track:', error);
                });
        }
    }
    
    /**
     * Add tracks to the queue
     * @param {Array} tracks - Array of track objects with file_path property
     * @param {boolean} playNow - Whether to play the first track immediately
     */
    addToQueue(tracks, playNow = false) {
        if (!tracks || tracks.length === 0) return;
        
        // Get just the file paths
        const paths = tracks.map(t => t.file_path);
        
        // Add to queue
        this.queue = [...this.queue, ...paths];
        
        if (playNow) {
            this.currentTrackIndex = this.queue.length - paths.length;
            this.playTrack(this.queue[this.currentTrackIndex], false);
        }
    }
    
    /**
     * Replace the current queue with new tracks
     * @param {Array} tracks - Array of track objects with file_path property
     * @param {boolean} playNow - Whether to play the first track immediately
     */
    replaceQueue(tracks, playNow = true) {
        if (!tracks || tracks.length === 0) return;
        
        // Get just the file paths
        const paths = tracks.map(t => t.file_path);
        
        // Replace queue
        this.queue = [...paths];
        
        if (playNow) {
            this.currentTrackIndex = 0;
            this.playTrack(this.queue[this.currentTrackIndex], false);
        } else {
            this.currentTrackIndex = 0;
        }
    }
    
    /**
     * Clear the queue
     */
    clearQueue() {
        this.queue = [];
        this.currentTrackIndex = -1;
    }
    
    /**
     * Get the current queue
     * @returns {Array} Array of track file paths
     */
    getQueue() {
        return this.queue;
    }
    
    /**
     * Get current state of the player
     * @returns {Object} Player state
     */
    getState() {
        return {
            isPlaying: this.isPlaying,
            currentTrackId: this.currentTrackId,
            currentTrackIndex: this.currentTrackIndex,
            queueLength: this.queue.length,
            currentTime: this.audioPlayer ? this.audioPlayer.currentTime : 0,
            duration: this.audioPlayer ? this.audioPlayer.duration : 0
        };
    }
}

/**
 * Initialize page-specific functionality
 */
function initializeCurrentPage() {
    // Detect current page and initialize specific functionality
    const path = window.location.pathname;
    
    if (path === '/' || path.includes('/home')) {
        console.log('Initializing home page');
        // Home page initialization if needed
    } else if (path.includes('/library')) {
        console.log('Initializing library page');
        // Library page is initialized via library.js
    } else if (path.includes('/settings')) {
        console.log('Initializing settings page');
        // Settings page is initialized via settings.js
    }
}

document.addEventListener('DOMContentLoaded', function() {
  // Cache DOM elements
  const searchInput = document.getElementById('search-input');
  const searchButton = document.getElementById('search-button');
  const exploreLink = document.getElementById('explore-link');
  const searchResultsList = document.getElementById('search-results-list');
  const exploreList = document.getElementById('explore-list');
  const playlistTracks = document.getElementById('playlist-tracks');
  const numTracksSelect = document.getElementById('num-tracks');
  const regenerateButton = document.getElementById('regenerate-playlist');
  const playlistTitle = document.getElementById('playlist-title');
  
  // Sections
  const welcomeSection = document.getElementById('welcome-section');
  const searchResultsSection = document.getElementById('search-results');
  const exploreSection = document.getElementById('explore-section');
  const playlistSection = document.getElementById('playlist-section');
  
  // Track player elements
  const trackName = document.querySelector('.track-name');
  const trackArtist = document.querySelector('.track-artist');
  
  // Current state
  let currentSeedTrackId = null;
  let currentPlaylistTracks = [];
  
  // Search functionality
  searchButton.addEventListener('click', performSearch);
  searchInput.addEventListener('keypress', function(e) {
    if (e.key === 'Enter') {
      performSearch();
    }
  });
  
  function performSearch() {
    const query = searchInput.value.trim();
    if (query) {
      fetch(`/search?query=${encodeURIComponent(query)}`)
        .then(response => response.json())
        .then(tracks => {
          displaySearchResults(tracks);
        })
        .catch(error => console.error('Error searching tracks:', error));
    }
  }
  
  function displaySearchResults(tracks) {
    searchResultsList.innerHTML = '';
    
    if (tracks.length === 0) {
      searchResultsList.innerHTML = '<p>No tracks found matching your search.</p>';
    } else {
      tracks.forEach(track => {
        const trackCard = createTrackCard(track);
        searchResultsList.appendChild(trackCard);
      });
    }
    
    // Show search results section, hide others
    showSection(searchResultsSection);
  }
  
  // Explore functionality
  exploreLink.addEventListener('click', function(e) {
    e.preventDefault();
    fetchExplore();
  });
  
  function fetchExplore() {
    fetch('/explore')
      .then(response => response.json())
      .then(tracks => {
        displayExplore(tracks);
      })
      .catch(error => console.error('Error getting explore tracks:', error));
  }
  
  function displayExplore(tracks) {
    exploreList.innerHTML = '';
    
    if (tracks.length === 0) {
      exploreList.innerHTML = '<p>No tracks available for exploration. Try adding some music first!</p>';
    } else {
      tracks.forEach(track => {
        const trackCard = createTrackCard(track);
        exploreList.appendChild(trackCard);
      });
    }
    
    // Show explore section, hide others
    showSection(exploreSection);
  }
  
  // Generate playlist functionality
  function generatePlaylist(seedTrackId, numTracks) {
    currentSeedTrackId = seedTrackId;
    
    fetch(`/playlist?seed_track_id=${seedTrackId}&num_tracks=${numTracks}`)
      .then(response => response.json())
      .then(playlist => {
        displayPlaylist(playlist);
      })
      .catch(error => console.error('Error generating playlist:', error));
  }
  
  function displayPlaylist(playlist) {
    currentPlaylistTracks = playlist;
    playlistTracks.innerHTML = '';
    
    if (playlist.length === 0 || playlist.error) {
      playlistTracks.innerHTML = '<p>Error generating playlist. Please try another track.</p>';
    } else {
      // Update playlist title with seed track
      const seedTrack = playlist[0];
      playlistTitle.textContent = `Playlist based on "${seedTrack.title || 'Unknown'}"`;
      
      // Display each track
      playlist.forEach((track, index) => {
        const trackItem = document.createElement('div');
        trackItem.className = 'track-card';
        trackItem.innerHTML = `
          <div class="album-art">
            <i class="fas fa-music"></i>
            <div class="play-overlay">
              <i class="fas fa-play"></i>
            </div>
          </div>
          <div class="track-title">${index + 1}. ${track.title || 'Unknown'}</div>
          <div class="track-artist">${track.artist || 'Unknown Artist'}</div>
          <div class="track-album">${track.album || 'Unknown Album'}</div>
        `;
        
        // When clicking a track in the playlist
        trackItem.addEventListener('click', function() {
          // In a real app, this would play the track
          trackName.textContent = track.title || 'Unknown';
          trackArtist.textContent = track.artist || 'Unknown Artist';
        });
        
        playlistTracks.appendChild(trackItem);
      });
    }
    
    // Show playlist section, hide others
    showSection(playlistSection);
  }
  
  // Regenerate the playlist with potentially different number of tracks
  regenerateButton.addEventListener('click', function() {
    if (currentSeedTrackId) {
      const numTracks = parseInt(numTracksSelect.value);
      generatePlaylist(currentSeedTrackId, numTracks);
    }
  });
  
  // Helper function to create a track card
  function createTrackCard(track) {
    const trackCard = document.createElement('div');
    trackCard.className = 'track-card';
    trackCard.innerHTML = `
      <div class="album-art">
        <i class="fas fa-music"></i>
        <div class="play-overlay">
          <i class="fas fa-play"></i>
        </div>
      </div>
      <div class="track-title">${track.title || 'Unknown'}</div>
      <div class="track-artist">${track.artist || 'Unknown Artist'}</div>
      <div class="track-album">${track.album || 'Unknown Album'}</div>
    `;
    
    // When clicking a track
    trackCard.addEventListener('click', function() {
      // Generate playlist with this track as seed
      const numTracks = parseInt(numTracksSelect.value);
      generatePlaylist(track.id, numTracks);
      
      // Update player bar info
      trackName.textContent = track.title || 'Unknown';
      trackArtist.textContent = track.artist || 'Unknown Artist';
    });
    
    return trackCard;
  }
  
  // Helper function to show a section and hide others
  function showSection(sectionToShow) {
    // Hide all sections
    welcomeSection.style.display = 'none';
    searchResultsSection.style.display = 'none';
    exploreSection.style.display = 'none';
    playlistSection.style.display = 'none';
    
    // Show the requested section
    sectionToShow.style.display = 'block';
  }
  
  // Load explore tracks on initial load
  fetchExplore();
});