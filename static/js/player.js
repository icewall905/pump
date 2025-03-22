// Simple version focused on loading tracks

// Track current playlist
let currentPlaylist = [];

// First, the displaySearchResults function needs to be made globally accessible
// Add this outside the DOMContentLoaded event handler
function displaySearchResults(tracks) {
    console.log('Displaying tracks:', tracks);
    const searchResults = document.getElementById('search-results');
    
    if (!searchResults) {
        console.error('Search results element not found');
        return;
    }
    
    searchResults.innerHTML = '';
    
    if (tracks.length === 0) {
        searchResults.innerHTML = '<p>No tracks found.</p>';
        return;
    }
    
    const resultsContainer = document.createElement('div');
    resultsContainer.className = 'track-grid';
    
    tracks.forEach(track => {
        console.log('Creating card for track:', track.title);
        const trackCard = createTrackCard(track);
        resultsContainer.appendChild(trackCard);
    });
    
    searchResults.appendChild(resultsContainer);
}

// Then make createTrackCard globally accessible as well
function createTrackCard(track) {
    const trackCard = document.createElement('div');
    trackCard.className = 'track-card';
    
    // Create album art container with image
    const albumArt = document.createElement('div');
    albumArt.className = 'album-art';
    
    const img = document.createElement('img');
    if (track.album_art_url) {
        let imgSrc = track.album_art_url;
        
        // If it starts with album_art_cache, convert to web-accessible URL
        if (imgSrc.includes('album_art_cache/') || imgSrc.includes('album_art_cache\\')) {
            // Extract the filename only
            const parts = imgSrc.split(/[\/\\]/);
            const filename = parts[parts.length - 1];
            imgSrc = `/cache/${filename}`;
        }
        // If it's an external URL, route through proxy
        else if (imgSrc.startsWith('http')) {
            imgSrc = `/albumart/${encodeURIComponent(imgSrc)}`;
        }
        
        img.src = imgSrc;
    } else {
        img.src = '/static/images/default-album-art.png';
    }
    img.alt = 'Album Art';
    img.onerror = function() {
        this.src = '/static/images/default-album-art.png';
    };
    
    const playOverlay = document.createElement('div');
    playOverlay.className = 'play-overlay';
    playOverlay.innerHTML = '<i class="play-icon">▶</i>';
    
    albumArt.appendChild(img);
    albumArt.appendChild(playOverlay);
    trackCard.appendChild(albumArt);
    
    // Create track info container
    const trackInfo = document.createElement('div');
    trackInfo.className = 'track-info';
    
    const trackTitle = document.createElement('div');
    trackTitle.className = 'track-title';
    trackTitle.textContent = track.title || 'Unknown Title';
    
    const trackArtist = document.createElement('div');
    trackArtist.className = 'track-artist';
    trackArtist.textContent = track.artist || 'Unknown Artist';
    
    trackInfo.appendChild(trackTitle);
    trackInfo.appendChild(trackArtist);
    
    // Create actions container with all buttons
    const trackActions = document.createElement('div');
    trackActions.className = 'track-actions';
    
    // Play button
    const playButton = document.createElement('button');
    playButton.className = 'play-track';
    playButton.textContent = 'Play';
    playButton.dataset.id = track.id;
    playButton.addEventListener('click', function(e) {
        e.stopPropagation();
        if (typeof window.playTrack === 'function') {
            window.playTrack(track.id);
        } else if (typeof playTrack === 'function') {
            playTrack(track);
        }
    });
    
    // Station button
    const stationButton = document.createElement('button');
    stationButton.className = 'create-station';
    stationButton.textContent = 'Station';
    stationButton.dataset.id = track.id;
    stationButton.addEventListener('click', function(e) {
        e.stopPropagation();
        // Always show the playlist container when creating a station
        const playlistContainer = document.getElementById('playlist-container');
        if (playlistContainer) {
            playlistContainer.style.display = 'block';
        }
        // Use the global createStation function
        createStation(track.id);
    });
    
    // Like button
    const likeButton = document.createElement('button');
    likeButton.className = track.liked ? 'track-like-button liked' : 'track-like-button';
    likeButton.innerHTML = track.liked ? '♥' : '♡';
    likeButton.title = track.liked ? 'Unlike' : 'Like';
    likeButton.dataset.id = track.id;
    likeButton.addEventListener('click', function(e) {
        e.stopPropagation();
        toggleLikeStatus(track.id);
    });
    
    // Add all buttons to actions container
    trackActions.appendChild(playButton);
    trackActions.appendChild(stationButton);
    trackActions.appendChild(likeButton);
    
    // Add actions to track info
    trackInfo.appendChild(trackActions);
    trackCard.appendChild(trackInfo);
    
    // Make the whole card clickable to play
    trackCard.addEventListener('click', function() {
        if (typeof window.playTrack === 'function') {
            window.playTrack(track.id);
        } else if (typeof playTrack === 'function') {
            playTrack(track);
        }
    });
    
    return trackCard;
}

// And finally, update the loadLiked function to use these global functions
function loadLiked() {
    console.log('loadLiked called');
    
    // Update heading
    const resultsHeading = document.getElementById('results-heading');
    if (resultsHeading) {
        resultsHeading.textContent = 'Liked Tracks';
    }
    
    const searchResults = document.getElementById('search-results');
    // Show loading indicator
    if (searchResults) {
        searchResults.innerHTML = '<div class="loading">Loading liked tracks...</div>';
    }
    
    // Hide the playlist container initially, but keep it in the DOM
    const playlistContainer = document.getElementById('playlist-container');
    if (playlistContainer) {
        playlistContainer.style.display = 'none';
    }
    
    // Fetch liked tracks
    fetch('/api/liked-tracks')
        .then(response => response.json())
        .then(data => {
            console.log('Liked tracks data:', data);
            
            // Handle empty results
            if (!Array.isArray(data) || data.length === 0) {
                if (searchResults) {
                    searchResults.innerHTML = `
                        <div class="empty-state">
                            <h3>No liked tracks found</h3>
                            <p>Like some tracks to see them appear here.</p>
                        </div>
                    `;
                }
                return;
            }
            
            // Ensure all tracks have the liked property set to true
            const likedTracks = data.map(track => ({
                ...track,
                liked: true
            }));
            
            // Set currentPlaylist so Save Playlist works
            window.currentPlaylist = likedTracks;
            
            // Enable save playlist button
            const savePlaylistBtn = document.getElementById('save-playlist-btn');
            if (savePlaylistBtn) {
                savePlaylistBtn.disabled = false;
            }
            
            // Display the tracks in a grid format
            displayTracksInGrid(likedTracks, searchResults);
        })
        .catch(error => {
            console.error('Error loading liked tracks:', error);
            if (searchResults) {
                searchResults.innerHTML = `<div class="error">Error loading liked tracks: ${error}</div>`;
            }
        });
}

// Add the toggleLikeStatus function if it doesn't exist in the global scope
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
        
        // Update all like buttons for this track
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
        
        // Update now playing like button if this is the current track
        const nowPlayingLikeButton = document.getElementById('like-track');
        if (nowPlayingLikeButton && window.currentTrackId === trackId) {
            if (data.liked) {
                nowPlayingLikeButton.classList.add('liked');
                nowPlayingLikeButton.innerHTML = '♥';
                nowPlayingLikeButton.title = 'Unlike';
            } else {
                nowPlayingLikeButton.classList.remove('liked');
                nowPlayingLikeButton.innerHTML = '♡';
                nowPlayingLikeButton.title = 'Like';
            }
        }
    })
    .catch(error => {
        console.error('Error toggling like status:', error);
    });
}

// Add this near the top of the file, outside any other functions

// Make createStation a global function that's accessible from anywhere
function createStation(trackId) {
    if (!trackId) return;
    
    console.log('Creating station for track ID:', trackId);
    
    // Show the playlist container if it exists
    const playlistContainer = document.getElementById('playlist-container');
    if (playlistContainer) {
        playlistContainer.style.display = 'block';
    }
    
    // Show loading state in the playlist
    const playlist = document.getElementById('playlist');
    if (playlist) {
        playlist.innerHTML = '<div class="loading">Creating station based on this track...</div>';
    }
    
    // Get configured station size from settings if available
    const stationSize = window.stationSize || 20; // Default to 20 if not set
    
    // Fetch station tracks from our API endpoint
    fetch(`/api/station/${trackId}?num_tracks=${stationSize}`)
        .then(response => {
            console.log('Station response received:', response.status);
            if (!response.ok) {
                throw new Error(`Server returned ${response.status}: ${response.statusText}`);
            }
            return response.json();
        })
        .then(data => {
            console.log('Station data received:', data);
            if (Array.isArray(data) && data.length > 0) {
                // Store tracks in currentPlaylist
                window.currentPlaylist = data;
                
                // Display the tracks in the playlist
                displayPlaylist(data);
                
                // Update playlist header with seed track information
                const seedTrack = data[0];
                const playlistHeader = document.querySelector('.playlist-header h2');
                if (playlistHeader) {
                    playlistHeader.textContent = `Station: ${seedTrack.artist || 'Unknown'} - ${seedTrack.title || 'Unknown'} (${data.length} tracks)`;
                }
                
                // Enable save playlist button
                const savePlaylistBtn = document.getElementById('save-playlist-btn');
                if (savePlaylistBtn) {
                    savePlaylistBtn.disabled = false;
                }
            } else if (data.error) {
                // Show error message
                if (playlist) {
                    playlist.innerHTML = `<div class="error">Error creating station: ${data.error}</div>`;
                }
            } else {
                // Empty array but no error
                if (playlist) {
                    playlist.innerHTML = '<div class="empty-state">Could not create station. No similar tracks found.</div>';
                }
            }
        })
        .catch(error => {
            console.error('Error creating station:', error);
            if (playlist) {
                playlist.innerHTML = `<div class="error">Failed to create station: ${error.message}</div>`;
            }
        });
}

// Also ensure displayPlaylist is globally accessible
function displayPlaylist(tracks) {
    const playlist = document.getElementById('playlist');
    if (!playlist) return;
    
    playlist.innerHTML = '';
    
    if (!Array.isArray(tracks) || tracks.length === 0) {
        playlist.innerHTML = '<p>No tracks in playlist.</p>';
        return;
    }
    
    // Create a grid container for the tracks
    const trackGrid = document.createElement('div');
    trackGrid.className = 'track-grid';
    
    // Create track cards for each track
    tracks.forEach((track, index) => {
        const trackCard = document.createElement('div');
        trackCard.className = 'track-card';
        trackCard.dataset.index = index;
        
        // Handle album art URL
        let trackArtUrl = track.album_art_url || '/static/images/default-album-art.png';
        // Handle cache paths
        if (trackArtUrl.includes('album_art_cache/') || trackArtUrl.includes('album_art_cache\\')) {
            const parts = trackArtUrl.split(/[\/\\]/);
            const filename = parts[parts.length - 1];
            trackArtUrl = `/cache/${filename}`;
        } else if (trackArtUrl.startsWith('http')) {
            trackArtUrl = `/albumart/${encodeURIComponent(trackArtUrl)}`;
        }
        
        // Create album art
        const albumArt = document.createElement('div');
        albumArt.className = 'album-art';
        
        const img = document.createElement('img');
        img.src = trackArtUrl;
        img.alt = 'Album Art';
        img.onerror = function() {
            this.src = '/static/images/default-album-art.png';
        };
        
        const playOverlay = document.createElement('div');
        playOverlay.className = 'play-overlay';
        playOverlay.innerHTML = '<i class="play-icon">▶</i>';
        
        albumArt.appendChild(img);
        albumArt.appendChild(playOverlay);
        
        // Create info div
        const trackInfo = document.createElement('div');
        trackInfo.className = 'track-info';
        
        const trackTitle = document.createElement('div');
        trackTitle.className = 'track-title';
        trackTitle.textContent = track.title || 'Unknown Title';
        
        const trackArtist = document.createElement('div');
        trackArtist.className = 'track-artist';
        trackArtist.textContent = track.artist || 'Unknown Artist';
        
        // Create actions
        const trackActions = document.createElement('div');
        trackActions.className = 'track-actions';
        
        const playButton = document.createElement('button');
        playButton.className = 'play-track';
        playButton.textContent = 'Play';
        playButton.dataset.index = index;
        
        trackActions.appendChild(playButton);
        
        // Add elements to card
        trackInfo.appendChild(trackTitle);
        trackInfo.appendChild(trackArtist);
        trackInfo.appendChild(trackActions);
        
        trackCard.appendChild(albumArt);
        trackCard.appendChild(trackInfo);
        
        // Add click event to play track
        trackCard.addEventListener('click', function() {
            playTrackFromPlaylist(index);
        });
        
        // Add to grid
        trackGrid.appendChild(trackCard);
    });
    
    playlist.appendChild(trackGrid);
    
    // Add click event for play buttons
    document.querySelectorAll('.play-track').forEach(button => {
        button.addEventListener('click', function(e) {
            e.stopPropagation();
            const index = parseInt(this.dataset.index);
            playTrackFromPlaylist(index);
        });
    });
}

// Helper function to play a track from the playlist
function playTrackFromPlaylist(index) {
    if (!window.currentPlaylist || !window.currentPlaylist[index]) return;
    
    const track = window.currentPlaylist[index];
    
    if (typeof window.playTrack === 'function') {
        window.playTrack(track.id);
    } else {
        console.error('playTrack function not available');
    }
}

// Add this to optimize album art loading
function optimizeImageLoading(imgElement, src) {
    // Create a low-priority image loader
    const loader = new Image();
    
    // Set up load handler before setting src
    loader.onload = function() {
        // Only update the main image when loading completes
        if (imgElement) {
            imgElement.src = src;
        }
    };
    
    loader.onerror = function() {
        // Fallback to default on error
        if (imgElement) {
            imgElement.src = '/static/images/default-album-art.png';
        }
    };
    
    // Low priority loading
    if ('fetchPriority' in loader) {
        loader.fetchPriority = 'low';
    }
    
    // Start loading
    loader.src = src;
}

// Update the displayTracksInGrid function to use lazy loading and optimized image loading
function displayTracksInGrid(tracks, container) {
    if (!container) return;
    
    container.innerHTML = '';
    
    // Create track grid
    const trackGrid = document.createElement('div');
    trackGrid.className = 'track-grid';
    
    // Only render visible tracks initially (virtual rendering)
    const initialVisibleCount = Math.min(20, tracks.length);
    
    // Add initial visible tracks to grid
    for (let i = 0; i < initialVisibleCount; i++) {
        const trackCard = createOptimizedTrackCard(tracks[i]);
        trackGrid.appendChild(trackCard);
    }
    
    // Add grid to container
    container.appendChild(trackGrid);
    
    // Setup intersection observer for infinite scrolling if there are more tracks
    if (tracks.length > initialVisibleCount) {
        setupInfiniteScroll(trackGrid, tracks, initialVisibleCount);
    }
    
    // Add Play All button at the top
    const actionButton = document.createElement('div');
    actionButton.className = 'liked-actions-container';
    actionButton.innerHTML = `
        <button class="primary-button" id="play-all-liked-btn">Play All Tracks</button>
    `;
    container.insertBefore(actionButton, trackGrid);
    
    // Add event listener for Play All button
    document.getElementById('play-all-liked-btn')?.addEventListener('click', function() {
        if (window.currentPlaylist && window.currentPlaylist.length > 0) {
            if (typeof window.playEntirePlaylist === 'function') {
                window.playEntirePlaylist(window.currentPlaylist);
            } else {
                // Fallback to playing the first track
                if (typeof window.playTrack === 'function' && window.currentPlaylist[0]) {
                    window.playTrack(window.currentPlaylist[0].id);
                }
            }
        }
    });
}

// Optimized track card creation
function createOptimizedTrackCard(track) {
    const trackCard = document.createElement('div');
    trackCard.className = 'track-card';
    
    // Create album art container with image placeholder
    const albumArt = document.createElement('div');
    albumArt.className = 'album-art';
    
    // Create image with lazy loading
    const img = document.createElement('img');
    img.alt = 'Album Art';
    img.loading = "lazy"; // Use browser's lazy loading
    img.src = '/static/images/default-album-art.png'; // Start with default
    
    if (track.album_art_url) {
        // Process image URL but delay actual loading
        let imgSrc = track.album_art_url;
        
        if (imgSrc.includes('album_art_cache/') || imgSrc.includes('album_art_cache\\')) {
            const parts = imgSrc.split(/[\/\\]/);
            const filename = parts[parts.length - 1];
            imgSrc = `/cache/${filename}`;
        } else if (imgSrc.startsWith('http')) {
            imgSrc = `/albumart/${encodeURIComponent(imgSrc)}`;
        }
        
        // Set the data-src instead of src for delayed loading
        img.setAttribute('data-src', imgSrc);
        
        // Use intersection observer to load when visible
        if ('IntersectionObserver' in window) {
            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const image = entry.target;
                        image.src = image.dataset.src;
                        observer.unobserve(image);
                    }
                });
            });
            observer.observe(img);
        } else {
            // Fallback for browsers without IntersectionObserver
            setTimeout(() => { img.src = imgSrc; }, 100);
        }
    }
    
    // Create play overlay with hover effect
    const playOverlay = document.createElement('div');
    playOverlay.className = 'play-overlay';
    playOverlay.innerHTML = '<i class="play-icon">▶</i>';
    
    // Add elements to container
    albumArt.appendChild(img);
    albumArt.appendChild(playOverlay);
    trackCard.appendChild(albumArt);
    
    // Add track info

    return trackCard;
}

// Setup infinite scrolling
function setupInfiniteScroll(container, allTracks, startIndex) {
    // Create a sentinel element to observe
    const sentinel = document.createElement('div');
    sentinel.className = 'scroll-sentinel';
    sentinel.style.height = '10px';
    sentinel.style.width = '100%';
    container.appendChild(sentinel);
    
    // Function to load more items
    let isLoading = false;
    let currentIndex = startIndex;
    
    function loadMoreItems() {
        if (isLoading || currentIndex >= allTracks.length) return;
        
        isLoading = true;
        const fragment = document.createDocumentFragment();
        
        // Load next batch
        const batchSize = 10;
        const endIndex = Math.min(currentIndex + batchSize, allTracks.length);
        
        for (let i = currentIndex; i < endIndex; i++) {
            const trackCard = createOptimizedTrackCard(allTracks[i]);
            fragment.appendChild(trackCard);
        }
        
        // Insert before sentinel
        container.insertBefore(fragment, sentinel);
        currentIndex = endIndex;
        isLoading = false;
    }
    
    // Create intersection observer
    const observer = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting) {
            loadMoreItems();
        }
    });
    
    // Start observing
    observer.observe(sentinel);
}

window.initPlayerPage = function() {
    // Moved all DOMContentLoaded logic here
    document.addEventListener('DOMContentLoaded', function() {
        console.log('DOM loaded - initializing player.js');
        
        // Immediate check for liked view
        const urlParams = new URLSearchParams(window.location.search);
        const view = urlParams.get('view');
        
        if (view === 'liked') {
            console.log('Detected liked view, loading liked tracks immediately');
            setTimeout(() => {
                loadLiked();
            }, 100); // Small delay to ensure DOM is ready
        }
        
        // DOM elements
        const searchInput = document.getElementById('search-input');
        const searchButton = document.getElementById('search-button');
        const searchResults = document.getElementById('search-results');
        const playlist = document.getElementById('playlist');
        const exploreLink = document.getElementById('explore-link');
        const recentLink = document.getElementById('recent-link');
        const resultsContainer = document.querySelector('.results-container');
        const savePlaylistBtn = document.getElementById('save-playlist-btn');
        const analyzeStatus = document.getElementById('analyze-status');
        const homeLink = document.getElementById('home-link'); // Add this line
        const libraryLink = document.getElementById('library-link');
        const settingsLink = document.getElementById('settings-link');
        
        // Check for DOM elements that should exist
        console.log('DOM elements found:', {
            searchResults: !!searchResults,
            exploreLink: !!exploreLink,
            recentLink: !!recentLink,
            resultsContainer: !!resultsContainer
        });
        
        // Add this near the start of your DOMContentLoaded function
        const playlistId = urlParams.get('playlist');
    
        // Function to set active navigation link
        function setActiveNav(view) {
            console.log('Setting active nav:', view);
            
            // First, remove active class from ALL nav links
            const allNavLinks = document.querySelectorAll('.sidebar-nav a');
            allNavLinks.forEach(link => link.classList.remove('active'));
            
            // Then add active class based on the view
            if (view === 'explore' && exploreLink) {
                exploreLink.classList.add('active');
            } else if (view === 'recent' && recentLink) {
                recentLink.classList.add('active');
            } else if (view === 'library' && libraryLink) {
                libraryLink.classList.add('active');
            } else if (view === 'settings' && settingsLink) {
                settingsLink.classList.add('active');
            } else if ((view === 'home' || !view) && homeLink) {
                homeLink.classList.add('active');
            }
        }
    
        // INITIALIZE UI based on URL parameters - THIS IS THE ONLY PLACE WE CHECK URL PARAMS
        if (playlistId) {
            console.log(`Loading playlist ${playlistId} from URL parameter`);
            loadPlaylist(playlistId);
            setActiveNav('home'); // Playlists shown on home
        } else if (view === 'explore') {
            console.log('Loading explore view from URL parameter');
            loadExplore();
            setActiveNav('explore');
        } else if (view === 'recent') {
            console.log('Loading recent view from URL parameter');
            loadRecent();
            setActiveNav('recent');
        } else if (view === 'home') {
            console.log('Loading home view');
            loadExplore(); // Home shows explore content
            setActiveNav('home');
        } else if (view === 'liked') {
            console.log('Loading liked tracks view');
            loadLiked();
            setActiveNav('liked');
        } else {
            // Default view (no parameter)
            console.log('Loading default home view');
            loadExplore();
            setActiveNav('home');
        }
        
        // COMMENT OUT THESE CLICK HANDLERS - they're handled in navigation.js
        /*
        if (exploreLink) {
            exploreLink.addEventListener('click', function(e) {
                e.preventDefault();
                // Existing code...
            });
        }
        
        if (recentLink) {
            recentLink.addEventListener('click', function(e) {
                e.preventDefault();
                // Existing code...
            });
        }
        */
    
        // Load playlists sidebar
        loadPlaylists();
        
        // Add this function inside your DOMContentLoaded handler
        function showAnalyzeStatus(message, type) {
            console.log(`Status: ${message} (${type})`);
            if (!analyzeStatus) {
                console.error('Analyze status element not found');
                return;
            }
            
            let className = '';
            switch (type) {
                case 'progress':
                    className = 'status-progress';
                    break;
                case 'error':
                    className = 'status-error';
                    break;
                case 'success':
                    className = 'status-success';
                    break;
                case 'info':
                    className = 'status-info';
                    break;
            }
            
            analyzeStatus.innerHTML = `<div class="${className}">${message}</div>`;
        }
        
        console.log('DOM elements found:', {
            searchResults: !!searchResults,
            exploreLink: !!exploreLink,
            recentLink: !!recentLink,
            resultsContainer: !!resultsContainer
        });
        
        // Event listeners
        if (searchButton) {
            searchButton.addEventListener('click', function() {
                const query = searchInput.value.trim();
                if (query) {
                    searchTracks(query);
                }
            });
        }
        
        if (searchInput) {
            searchInput.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    const query = searchInput.value.trim();
                    if (query) {
                        searchTracks(query);
                    }
                }
            });
        }
        
        if (exploreLink) {
            exploreLink.addEventListener('click', function(e) {
                e.preventDefault();
                loadExplore();
                setActiveNav('explore');
            });
        }
        
        if (recentLink) {
            recentLink.addEventListener('click', function(e) {
                e.preventDefault();
                loadRecent();
                setActiveNav('recent');
            });
        }
        
        // Add this with your other initialization code
        loadPlaylists();
        
        // Add these with your other initialization code
        const savePlaylistModal = document.getElementById('save-playlist-modal');
        const savePlaylistForm = document.getElementById('save-playlist-form');
        const closeModalBtn = savePlaylistModal ? savePlaylistModal.querySelector('.close') : null;
        
        // Save playlist button
        if (savePlaylistBtn) {
            savePlaylistBtn.addEventListener('click', function() {
                if (savePlaylistModal) {
                    savePlaylistModal.style.display = 'block';
                }
            });
        }
        
        // Close modal button
        if (closeModalBtn) {
            closeModalBtn.addEventListener('click', function() {
                if (savePlaylistModal) {
                    savePlaylistModal.style.display = 'none';
                }
            });
        }
        
        // Save playlist form
        if (savePlaylistForm) {
            savePlaylistForm.addEventListener('submit', function(e) {
                e.preventDefault();
                savePlaylist(); // Use the inner function instead of global
            });
        }
        
        // Close modal when clicking outside
        window.addEventListener('click', function(e) {
            if (savePlaylistModal && e.target === savePlaylistModal) {
                savePlaylistModal.style.display = 'none';
            }
        });
        
        // Functions
        function loadExplore() {
            console.log('loadExplore called');
            if (!searchResults || !resultsContainer) {
                console.error('Required DOM elements missing for loadExplore');
                return;
            }
    
            if (resultsContainer) {
                const heading = resultsContainer.querySelector('h2');
                if (heading) heading.textContent = 'Discover';
            }
            
            if (searchResults) {
                searchResults.innerHTML = '<div class="loading">Loading tracks...</div>';
            }
            
            console.log('Fetching /explore');
            fetch('/explore')
                .then(response => {
                    console.log('Explore response received:', response);
                    return response.json();
                })
                .then(data => {
                    console.log('Explore data:', data);
                    if (Array.isArray(data) && data.length > 0) {
                        // Limit to 6 items only
                        displaySearchResults(data.slice(0, 6));
                    } else if (Array.isArray(data) && data.length === 0) {
                        searchResults.innerHTML = '<p>No tracks found. Try adding some music!</p>';
                    } else if (data.error) {
                        searchResults.innerHTML = `<p>Error: ${data.error}</p>`;
                    }
                })
                .catch(error => {
                    console.error('Error loading explore:', error);
                    if (searchResults) {
                        searchResults.innerHTML = '<p>Failed to load tracks. See console for details.</p>';
                    }
                });
        }
        
        function loadRecent() {
            console.log('loadRecent called');
            if (resultsContainer) {
                const heading = resultsContainer.querySelector('h2');
                if (heading) heading.textContent = 'Recently Added';
            }
            
            if (searchResults) {
                searchResults.innerHTML = '<div class="loading">Loading recent tracks...</div>';
            }
            
            fetch('/recent')
                .then(response => {
                    console.log('Recent response received:', response);
                    return response.json();
                })
                .then(data => {
                    console.log('Recent data:', data);
                    if (Array.isArray(data) && data.length > 0) {
                        // Limit to 6 items only
                        displaySearchResults(data.slice(0, 6));
                    } else if (Array.isArray(data) && data.length === 0) {
                        searchResults.innerHTML = '<p>No recent tracks found. Try adding some music!</p>';
                    } else if (data.error) {
                        searchResults.innerHTML = `<p>Error: ${data.error}</p>`;
                    }
                })
                .catch(error => {
                    console.error('Error loading recent tracks:', error);
                    if (searchResults) {
                        searchResults.innerHTML = '<p>Failed to load recent tracks. See console for details.</p>';
                    }
                });
        }
        
        function searchTracks(query) {
            console.log(`Searching for: ${query}`);
            if (searchResults) {
                searchResults.innerHTML = '<div class="loading">Searching...</div>';
            }
            
            fetch(`/search?query=${encodeURIComponent(query)}`)
                .then(response => response.json())
                .then(data => {
                    console.log('Search results:', data);
                    if (Array.isArray(data)) {
                        displaySearchResults(data);
                    } else if (data.error) {
                        searchResults.innerHTML = `<p>Error: ${data.error}</p>`;
                    }
                })
                .catch(error => {
                    console.error('Error searching:', error);
                    if (searchResults) {
                        searchResults.innerHTML = '<p>Search failed. See console for details.</p>';
                    }
                });
        }
        
        function displaySearchResults(tracks) {
            console.log('Displaying tracks:', tracks);
            if (!searchResults) {
                console.error('Search results element not found');
                return;
            }
            
            searchResults.innerHTML = '';
            
            if (tracks.length === 0) {
                searchResults.innerHTML = '<p>No tracks found.</p>';
                return;
            }
            
            const resultsContainer = document.createElement('div');
            resultsContainer.className = 'track-grid';
            
            tracks.forEach(track => {
                console.log('Creating card for track:', track.title);
                const trackCard = createTrackCard(track);
                resultsContainer.appendChild(trackCard);
            });
            
            searchResults.appendChild(resultsContainer);
            
            // Add event listeners for buttons
            document.querySelectorAll('.create-station').forEach(button => {
                button.addEventListener('click', function() {
                    console.log('Create station clicked for track ID:', this.dataset.id);
                    createStation(this.dataset.id);
                });
            });
            
            document.querySelectorAll('.play-track').forEach(button => {
                button.addEventListener('click', function() {
                    console.log('Play track clicked for track ID:', this.dataset.id);
                    // Use the global playTrack function
                    if (typeof window.playTrack === 'function') {
                        window.playTrack(this.dataset.id);
                    } else {
                        console.error('playTrack function not available');
                    }
                });
            });
        }
        
        // Update the createStation function to work from any view, including the Liked view
    
        function createStation(trackId) {
            if (!trackId) return;
            
            console.log('Creating station for track ID:', trackId);
            
            // Show loading state in the playlist area
            const playlist = document.getElementById('playlist');
            const playlistContainer = document.getElementById('playlist-container');
            
            // Make sure playlist container is visible
            if (playlistContainer) {
                playlistContainer.style.display = 'block';
            }
            
            // Show loading state
            if (playlist) {
                playlist.innerHTML = '<div class="loading">Creating playlist based on this track...</div>';
            }
            
            // Reset any status messages
            const analyzeStatus = document.getElementById('analyze-status');
            if (analyzeStatus) {
                analyzeStatus.innerHTML = '<div class="status-progress">Creating station...</div>';
            }
            
            // Fetch the station tracks
            fetch(`/station/${trackId}`)
                .then(response => response.json())
                .then(data => {
                    if (Array.isArray(data) && data.length > 0) {
                        // Store tracks in currentPlaylist
                        currentPlaylist = data;
                        
                        // Display track list
                        displayPlaylist(data);
                        
                        // Set seed track information for header
                        const seedTrack = data[0];
                        const playlistHeader = document.querySelector('.playlist-header h2');
                        
                        if (playlistHeader) {
                            playlistHeader.textContent = `Station: ${seedTrack.artist || 'Unknown'} - ${seedTrack.title || 'Unknown'} (${data.length} tracks)`;
                        }
                        
                        // Enable save button
                        const savePlaylistBtn = document.getElementById('save-playlist-btn');
                        if (savePlaylistBtn) {
                            savePlaylistBtn.disabled = false;
                        }
                        
                        // Clear status
                        if (analyzeStatus) {
                            analyzeStatus.innerHTML = '';
                        }
                    } else if (data.error) {
                        if (analyzeStatus) {
                            analyzeStatus.innerHTML = `<div class="status-error">Error: ${data.error}</div>`;
                        }
                        if (playlist) {
                            playlist.innerHTML = `<div class="error">Error creating station: ${data.error}</div>`;
                        }
                    } else {
                        if (analyzeStatus) {
                            analyzeStatus.innerHTML = '<div class="status-error">Invalid response from server</div>';
                        }
                        if (playlist) {
                            playlist.innerHTML = '<div class="error">Failed to create station</div>';
                        }
                    }
                })
                .catch(error => {
                    console.error('Error creating station:', error);
                    if (analyzeStatus) {
                        analyzeStatus.innerHTML = '<div class="status-error">Failed to create playlist</div>';
                    }
                    if (playlist) {
                        playlist.innerHTML = `<div class="error">Error: ${error}</div>`;
                    }
                });
        }
        
        // Add displayPlaylist function if it doesn't exist
        function displayPlaylist(tracks) {
            console.log('Displaying playlist:', tracks);
            const playlist = document.getElementById('playlist');
            
            if (!playlist) {
                console.error('Playlist container not found');
                return;
            }
            
            playlist.innerHTML = '';
            
            if (!Array.isArray(tracks) || tracks.length === 0) {
                playlist.innerHTML = '<p>No tracks in playlist.</p>';
                return;
            }
            
            // Add Play All button at the top
            const playAllContainer = document.createElement('div');
            playAllContainer.className = 'playlist-controls';
            playAllContainer.innerHTML = `
                <button id="play-all-button" class="primary-button">
                    ▶️ Play All (${tracks.length} tracks)
                </button>
            `;
            playlist.appendChild(playAllContainer);
            
            // Add event listener to Play All button
            const playAllButton = document.getElementById('play-all-button');
            if (playAllButton) {
                playAllButton.addEventListener('click', function() {
                    playEntirePlaylist(tracks);
                });
            }
            
            const tracksContainer = document.createElement('div');
            tracksContainer.className = 'track-grid';
            
            tracks.forEach((track, index) => {
                const trackCard = document.createElement('div');
                trackCard.className = 'track-card';
                
                const artDiv = document.createElement('div');
                artDiv.className = 'track-art';
                
                // Add album art if available
                if (track.album_art_url) {
                    const img = document.createElement('img');
                    const imgUrl = track.album_art_url.startsWith('http') ? 
                        `/albumart/${encodeURIComponent(track.album_art_url)}` : track.album_art_url;
                    
                    img.src = imgUrl;
                    img.alt = track.album || track.title;
                    img.onerror = function() {
                        this.style.display = 'none';
                        artDiv.classList.add('default-art');
                        artDiv.innerHTML = `<div class="art-placeholder">${(track.artist || 'Unknown').charAt(0).toUpperCase()}</div>`;
                    };
                    artDiv.appendChild(img);
                } else {
                    // No album art URL, use placeholder
                    artDiv.classList.add('default-art');
                    artDiv.innerHTML = `<div class="art-placeholder">${(track.artist || 'Unknown').charAt(0).toUpperCase()}</div>`;
                }
                
                const infoDiv = document.createElement('div');
                infoDiv.className = 'track-info';
                infoDiv.innerHTML = `
                    <div class="track-title">${track.title || 'Unknown'}</div>
                    <div class="track-artist">${track.artist || 'Unknown'}</div>
                    <div class="track-album">${track.album || 'Unknown'}</div>
                `;
                
                const actionsDiv = document.createElement('div');
                actionsDiv.className = 'track-actions';
                actionsDiv.innerHTML = `
                    <div class="track-number">${index + 1}</div>
                    <button class="play-track" data-id="${track.id}">Play</button>
                `;
                
                trackCard.appendChild(artDiv);
                trackCard.appendChild(infoDiv);
                trackCard.appendChild(actionsDiv);
                
                tracksContainer.appendChild(trackCard);
            });
            
            playlist.appendChild(tracksContainer);
        }
        
        // Add the loadPlaylists function
        function loadPlaylists() {
            // Use the shared function if available
            if (typeof window.loadSidebarPlaylists === 'function') {
                window.loadSidebarPlaylists();
            }
            // Otherwise, fall back to the existing implementation
        }
        
        // Add these supporting functions
        function loadPlaylist(playlistId) {
            console.log(`Loading playlist ${playlistId}`);
            if (analyzeStatus) {
                showAnalyzeStatus('Loading playlist...', 'progress');
            }
            
            fetch(`/playlists/${playlistId}`)
                .then(response => response.json())
                .then(data => {
                    console.log('Loaded playlist:', data);
                    if (data.error) {
                        showAnalyzeStatus(`Error: ${data.error}`, 'error');
                        return;
                    }
                    
                    // Store current playlist
                    currentPlaylist = data.tracks;
                    
                    // Display the playlist
                    displayPlaylist(data.tracks);
                    
                    // Update header with playlist name
                    const playlistHeader = document.querySelector('.playlist-container h2');
                    if (playlistHeader) {
                        playlistHeader.textContent = `Playlist: ${data.name}`;
                    }
                    
                    // Enable save button
                    const savePlaylistBtn = document.getElementById('save-playlist-btn');
                    if (savePlaylistBtn) {
                        savePlaylistBtn.disabled = false;
                    }
                    
                    // Clear status
                    if (analyzeStatus) {
                        setTimeout(() => {
                            analyzeStatus.innerHTML = '';
                        }, 2000);
                    }
                })
                .catch(error => {
                    console.error('Error loading playlist:', error);
                    showAnalyzeStatus('Failed to load playlist', 'error');
                });
        }
        
        function deletePlaylist(playlistId) {
            console.log(`Deleting playlist ${playlistId}`);
            
            fetch(`/playlists/${playlistId}`, {
                method: 'DELETE'
            })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    alert(`Error: ${data.error}`);
                } else {
                    // Refresh playlist list
                    loadPlaylists();
                }
            })
            .catch(error => {
                console.error('Error deleting playlist:', error);
                alert('Failed to delete playlist');
            });
        }
        
        // Make sure the global savePlaylist function has access to these
        window.showAnalyzeStatus = showAnalyzeStatus;
        window.analyzeStatus = analyzeStatus;
    
        // Define savePlaylist inside DOMContentLoaded
        function savePlaylist() {
            const playlistName = document.getElementById('playlist-name');
            const playlistDescription = document.getElementById('playlist-description');
            const savePlaylistModal = document.getElementById('save-playlist-modal');
            
            if (!playlistName) {
                console.error('Playlist name element not found');
                return;
            }
            
            // Check if we're on the liked tracks page
            const isLikedPage = window.location.href.includes('view=liked');
            
            // If currentPlaylist is empty but we're on liked page, try to reload liked tracks
            if ((!window.currentPlaylist || window.currentPlaylist.length === 0) && isLikedPage) {
                console.log('Reloading liked tracks for playlist save');
                
                fetch('/api/liked-tracks')
                    .then(response => response.json())
                    .then(data => {
                        if (Array.isArray(data) && data.length > 0) {
                            window.currentPlaylist = data;
                            // Try saving again
                            savePlaylist();
                        } else {
                            alert('No liked tracks found to save as playlist');
                        }
                    })
                    .catch(error => {
                        console.error('Error fetching liked tracks:', error);
                        alert('Error fetching liked tracks');
                    });
                return;
            }
            
            if (!window.currentPlaylist || window.currentPlaylist.length === 0) {
                alert('Cannot save an empty playlist');
                return;
            }
            
            const name = playlistName.value.trim();
            const description = playlistDescription ? playlistDescription.value.trim() : '';
            
            if (!name) {
                alert('Please enter a playlist name');
                return;
            }
            
            // Get track IDs
            const trackIds = window.currentPlaylist.map(track => track.id);
            
            // Save to server
            console.log('Saving playlist:', { name, description, tracks: trackIds.length });
            
            fetch('/playlists', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    name: name,
                    description: description,
                    tracks: trackIds
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    alert(`Error: ${data.error}`);
                } else {
                    // Close modal
                    if (savePlaylistModal) {
                        savePlaylistModal.style.display = 'none';
                    }
                    
                    // Reset form
                    if (playlistName) playlistName.value = '';
                    if (playlistDescription) playlistDescription.value = '';
                    
                    // Show success notification
                    alert(`Playlist "${name}" saved successfully`);
                    
                    // Refresh playlist list in sidebar
                    if (typeof window.loadSidebarPlaylists === 'function') {
                        window.loadSidebarPlaylists();
                    }
                }
            })
            .catch(error => {
                console.error('Error saving playlist:', error);
                alert('Failed to save playlist');
            });
        }
        
        // Expose the inner savePlaylist function to the window for any direct HTML onclick references
        window.savePlaylist = savePlaylist;
    
        // Rest of your existing initialization code...
    
        // Set up play button event listeners
        document.querySelectorAll('.play-track').forEach(button => {
            button.addEventListener('click', function() {
                const trackId = this.dataset.id;
                console.log('Play track clicked for track ID:', trackId);
                
                // Use the global playTrack function from player-controls.js
                if (typeof window.playTrack === 'function') {
                    window.playTrack(trackId);
                } else {
                    console.error('playTrack function not available');
                }
            });
        });
        
        // Additional player-specific functions can be added here
    
        // Make the Save Playlist button work on the Liked page
        if (view === 'liked') {
            // Show Save Playlist button when on liked page
            const playlistContainer = document.getElementById('playlist-container');
            const playlistHeader = document.querySelector('.playlist-header');
            const resultsContainer = document.querySelector('.results-container');
            
            if (playlistContainer) {
                // Only hide it, but keep the button accessible
                playlistContainer.style.display = 'none';
                
                // Add a custom save button to the results container instead
                const saveButton = document.createElement('div');
                saveButton.className = 'save-liked-actions';
                saveButton.innerHTML = `
                    <button id="save-liked-playlist-btn" class="primary-button">Save Liked as Playlist</button>
                `;
                
                if (resultsContainer) {
                    resultsContainer.insertBefore(saveButton, document.getElementById('search-results'));
                    
                    // Add click handler
                    document.getElementById('save-liked-playlist-btn').addEventListener('click', function() {
                        const modal = document.getElementById('save-playlist-modal');
                        if (modal) modal.style.display = 'block';
                    });
                }
            }
        }
    
        // Add these optimizations to your DOMContentLoaded event handler
    
        // Debounce function to prevent excessive UI updates
        function debounce(func, wait) {
            let timeout;
            return function(...args) {
                const context = this;
                clearTimeout(timeout);
                timeout = setTimeout(() => func.apply(context, args), wait);
            };
        }
    
        // Use requestAnimationFrame for smoother progress bar updates
        function updateSmoothProgress() {
            if (!audioPlayer || !progressFill || !currentTimeDisplay) return;
            
            const currentTime = audioPlayer.currentTime;
            const duration = audioPlayer.duration || 0;
            
            // Update progress bar
            if (duration > 0) {
                const percent = (currentTime / duration) * 100;
                progressFill.style.width = `${percent}%`;
            }
            
            // Only update time display every 500ms to reduce DOM updates
            if (!updateSmoothProgress.lastUpdate || Date.now() - updateSmoothProgress.lastUpdate > 500) {
                currentTimeDisplay.textContent = formatTime(currentTime);
                updateSmoothProgress.lastUpdate = Date.now();
            }
            
            // Schedule next update
            if (!audioPlayer.paused) {
                requestAnimationFrame(updateSmoothProgress);
            }
        }
    
        // Replace the existing updateProgress function
        function updateProgress() {
            requestAnimationFrame(updateSmoothProgress);
        }
    });
    
    // Make sure you have this function defined
    function displayPlaylistTracks(tracks) {
        const resultsContainer = document.querySelector('.results-container');
        if (!resultsContainer) return;
    
        // Clear previous results
        resultsContainer.innerHTML = '';
        
        if (!tracks || tracks.length === 0) {
            resultsContainer.innerHTML = '<div class="no-results">No tracks found in playlist</div>';
            return;
        }
        
        // Create grid for track cards
        const trackGrid = document.createElement('div');
        trackGrid.className = 'track-grid';
        
        // Add each track to the grid
        tracks.forEach(track => {
            const card = createTrackCard(track);
            trackGrid.appendChild(card);
        });
        
        // Add the grid to the results container
        resultsContainer.appendChild(trackGrid);
    }
    
    // Replace the createTrackCard function with this complete version
    function createTrackCard(track) {
        const trackCard = document.createElement('div');
        trackCard.className = 'track-card';
        
        // Create album art container with image
        const albumArt = document.createElement('div');
        albumArt.className = 'album-art';
        
        const img = document.createElement('img');
        if (track.album_art_url) {
            let imgSrc = track.album_art_url;
            
            // If it starts with album_art_cache, convert to web-accessible URL
            if (imgSrc.includes('album_art_cache/') || imgSrc.includes('album_art_cache\\')) {
                // Extract the filename only
                const parts = imgSrc.split(/[\/\\]/);
                const filename = parts[parts.length - 1];
                imgSrc = `/cache/${filename}`;
            }
            // If it's an external URL, route through proxy
            else if (imgSrc.startsWith('http')) {
                imgSrc = `/albumart/${encodeURIComponent(imgSrc)}`;
            }
            
            img.src = imgSrc;
        } else {
            img.src = '/static/images/default-album-art.png';
        }
        img.alt = 'Album Art';
        img.onerror = function() {
            this.src = '/static/images/default-album-art.png';
        };
        
        const playOverlay = document.createElement('div');
        playOverlay.className = 'play-overlay';
        playOverlay.innerHTML = '<i class="play-icon">▶</i>';
        
        albumArt.appendChild(img);
        albumArt.appendChild(playOverlay);
        trackCard.appendChild(albumArt);
        
        // Create track info container
        const trackInfo = document.createElement('div');
        trackInfo.className = 'track-info';
        
        const trackTitle = document.createElement('div');
        trackTitle.className = 'track-title';
        trackTitle.textContent = track.title || 'Unknown Title';
        
        const trackArtist = document.createElement('div');
        trackArtist.className = 'track-artist';
        trackArtist.textContent = track.artist || 'Unknown Artist';
        
        trackInfo.appendChild(trackTitle);
        trackInfo.appendChild(trackArtist);
        
        // Create actions container with all buttons
        const trackActions = document.createElement('div');
        trackActions.className = 'track-actions';
        
        // Play button
        const playButton = document.createElement('button');
        playButton.className = 'play-track';
        playButton.textContent = 'Play';
        playButton.dataset.id = track.id;
        playButton.addEventListener('click', function(e) {
            e.stopPropagation();
            if (typeof window.playTrack === 'function') {
                window.playTrack(track.id);
            } else if (typeof playTrack === 'function') {
                playTrack(track);
            }
        });
        
        // Station button
        const stationButton = document.createElement('button');
        stationButton.className = 'create-station';
        stationButton.textContent = 'Station';
        stationButton.dataset.id = track.id;
        stationButton.addEventListener('click', function(e) {
            e.stopPropagation();
            // Always show the playlist container when creating a station
            const playlistContainer = document.getElementById('playlist-container');
            if (playlistContainer) {
                playlistContainer.style.display = 'block';
            }
            // Use the global createStation function
            createStation(track.id);
        });
        
        // Like button
        const likeButton = document.createElement('button');
        likeButton.className = track.liked ? 'track-like-button liked' : 'track-like-button';
        likeButton.innerHTML = track.liked ? '♥' : '♡';
        likeButton.title = track.liked ? 'Unlike' : 'Like';
        likeButton.dataset.id = track.id;
        likeButton.addEventListener('click', function(e) {
            e.stopPropagation();
            toggleLikeStatus(track.id);
        });
        
        // Add all buttons to actions container
        trackActions.appendChild(playButton);
        trackActions.appendChild(stationButton);
        trackActions.appendChild(likeButton);
        
        // Add actions to track info
        trackInfo.appendChild(trackActions);
        trackCard.appendChild(trackInfo);
        
        // Make the whole card clickable to play
        trackCard.addEventListener('click', function() {
            if (typeof window.playTrack === 'function') {
                window.playTrack(track.id);
            } else if (typeof playTrack === 'function') {
                playTrack(track);
            }
        });
        
        return trackCard;
    }
    
    // Add this helper function
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
            
            // Update all like buttons for this track
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
            
            // Update now playing like button if this is the current track
            const nowPlayingLikeButton = document.getElementById('like-track');
            if (nowPlayingLikeButton && window.currentTrackId === trackId) {
                if (data.liked) {
                    nowPlayingLikeButton.classList.add('liked');
                    nowPlayingLikeButton.innerHTML = '♥';
                    nowPlayingLikeButton.title = 'Unlike';
                } else {
                    nowPlayingLikeButton.classList.remove('liked');
                    nowPlayingLikeButton.innerHTML = '♡';
                    nowPlayingLikeButton.title = 'Like';
                }
            }
        })
        .catch(error => {
            console.error('Error toggling like status:', error);
        });
    }
    
    // Update the image handling logic
    function displayTrack(track) {
        if (!track) return;
        
        const trackElement = document.createElement('div');
        trackElement.className = 'track-item';
        
        // Create track art container
        const artContainer = document.createElement('div');
        artContainer.className = 'track-art';
        
        // Create img element
        const img = document.createElement('img');
        img.alt = track.title || 'Track';
        
        if (track.album_art_url) {
            let imgSrc = track.album_art_url;
            
            // If it starts with album_art_cache, convert to web-accessible URL
            if (imgSrc.includes('album_art_cache/') || imgSrc.includes('album_art_cache\\')) {
                // Extract the filename only
                const parts = imgSrc.split(/[\/\\]/);
                const filename = parts[parts.length - 1];
                imgSrc = `/cache/${filename}`;
            }
            // If it's an external URL, route through proxy
            else if (imgSrc.startsWith('http')) {
                imgSrc = `/albumart/${encodeURIComponent(imgSrc)}`;
            }
            
            img.src = imgSrc;
        } else {
            // Use default image if no album art available
            img.src = '/static/images/default-album-art.png';
        }
        
        // Handle image loading errors
        img.onerror = function() {
            this.src = '/static/images/default-album-art.png';
        };
        
        artContainer.appendChild(img);
        trackElement.appendChild(artContainer);
        
        // Create track info container
        const infoContainer = document.createElement('div');
        infoContainer.className = 'track-info';
        
        // Add track title
        const titleElement = document.createElement('div');
        titleElement.className = 'track-title';
        titleElement.textContent = track.title || 'Unknown Title';
        
        // Add track artist
        const artistElement = document.createElement('div');
        artistElement.className = 'track-artist';
        artistElement.textContent = track.artist || 'Unknown Artist';
        
        // Add track album
        const albumElement = document.createElement('div');
        albumElement.className = 'track-album';
        albumElement.textContent = track.album || 'Unknown Album';
        
        // Add to info container
        infoContainer.appendChild(titleElement);
        infoContainer.appendChild(artistElement);
        infoContainer.appendChild(albumElement);
        
        // Create actions container
        const actionsContainer = document.createElement('div');
        actionsContainer.className = 'track-actions';
        
        // Add play button
        const playButton = document.createElement('button');
        playButton.className = 'play-button';
        playButton.innerHTML = '▶';
        playButton.addEventListener('click', function(e) {
            e.stopPropagation();
            playTrack(track);
        });
        
        // Add like button
        const likeButton = document.createElement('button');
        likeButton.className = track.liked ? 'track-like-button liked' : 'track-like-button';
        likeButton.innerHTML = track.liked ? '♥' : '♡';
        likeButton.title = track.liked ? 'Unlike' : 'Like';
        likeButton.setAttribute('data-id', track.id);
        likeButton.addEventListener('click', function(e) {
            e.stopPropagation();
            toggleLikeStatus(track.id);
        });
        
        actionsContainer.appendChild(playButton);
        actionsContainer.appendChild(likeButton);
        
        // Add to track element
        trackElement.appendChild(infoContainer);
        trackElement.appendChild(actionsContainer);
        
        // Add click event to play track when clicking on the track element
        trackElement.addEventListener('click', function() {
            playTrack(track);
        });
        
        return trackElement;
    }
    
    // Update the loadLiked function to preserve station functionality
    
    function loadLiked() {
        console.log('loadLiked called');
        
        // Update heading
        const resultsHeading = document.getElementById('results-heading');
        if (resultsHeading) {
            resultsHeading.textContent = 'Liked Tracks';
        }
        
        const searchResults = document.getElementById('search-results');
        // Show loading indicator
        if (searchResults) {
            searchResults.innerHTML = '<div class="loading">Loading liked tracks...</div>';
        }
        
        // Hide the playlist container initially, but keep it in the DOM
        const playlistContainer = document.getElementById('playlist-container');
        if (playlistContainer) {
            playlistContainer.style.display = 'none';
        }
        
        // Fetch liked tracks
        fetch('/api/liked-tracks')
            .then(response => response.json())
            .then(data => {
                console.log('Liked tracks data:', data);
                
                // Handle empty results
                if (!Array.isArray(data) || data.length === 0) {
                    if (searchResults) {
                        searchResults.innerHTML = `
                            <div class="empty-state">
                                <h3>No liked tracks found</h3>
                                <p>Like some tracks to see them appear here.</p>
                            </div>
                        `;
                    }
                    return;
                }
                
                // Ensure all tracks have the liked property set to true
                const likedTracks = data.map(track => ({
                    ...track,
                    liked: true
                }));
                
                // Set currentPlaylist so Save Playlist works
                window.currentPlaylist = likedTracks;
                
                // Enable save playlist button
                const savePlaylistBtn = document.getElementById('save-playlist-btn');
                if (savePlaylistBtn) {
                    savePlaylistBtn.disabled = false;
                }
                
                // Display the tracks in a grid format
                displayTracksInGrid(likedTracks, searchResults);
            })
            .catch(error => {
                console.error('Error loading liked tracks:', error);
                if (searchResults) {
                    searchResults.innerHTML = `<div class="error">Error loading liked tracks: ${error}</div>`;
                }
            });
    }
    
    // Helper function to display tracks in a grid
    function displayTracksInGrid(tracks, container) {
        if (!container) return;
        
        container.innerHTML = '';
        
        // Create track grid
        const trackGrid = document.createElement('div');
        trackGrid.className = 'track-grid';
        
        // Add tracks to grid
        tracks.forEach(track => {
            const trackCard = createTrackCard(track);
            trackGrid.appendChild(trackCard);
        });
        
        // Add grid to container
        container.appendChild(trackGrid);
        
        // Add a "Play All Liked" button instead of Save as Playlist
        const actionButton = document.createElement('div');
        actionButton.className = 'liked-actions-container';
        actionButton.innerHTML = `
            <button class="primary-button" id="play-all-liked-btn">Play All Liked Tracks</button>
        `;
        container.insertBefore(actionButton, trackGrid);
        
        // Add event listener to the play all button
        document.getElementById('play-all-liked-btn').addEventListener('click', function() {
            if (window.currentPlaylist && window.currentPlaylist.length > 0) {
                // Use the existing playEntirePlaylist function if available
                if (typeof window.playEntirePlaylist === 'function') {
                    window.playEntirePlaylist(window.currentPlaylist);
                } else {
                    // Fallback - play the first track
                    if (typeof window.playTrack === 'function' && window.currentPlaylist[0]) {
                        window.playTrack(window.currentPlaylist[0].id);
                    }
                }
            }
        });
    }
};

// Then add this at the very bottom:
document.addEventListener('DOMContentLoaded', function() {
    window.initPlayerPage();
});

window.loadExplore = function() {
    console.log('Global loadExplore called');
    // ...existing code...
    // Fetch explore data
    fetch('/explore')
        .then(response => response.json())
        .then(data => {
            // ...existing code...
        })
        .catch(error => {
            // ...existing code...
        });
};

window.loadRecent = function() {
    console.log('Global loadRecent called');
    // ...existing code...
    // Fetch recent data
    fetch('/recent')
        .then(response => response.json())
        .then(data => {
            // ...existing code...
        })
        .catch(error => {
            // ...existing code...
        });
};

window.loadLiked = function() {
    console.log('Global loadLiked called');
    // ...existing code...
    // Fetch liked tracks
    fetch('/api/liked-tracks')
        .then(response => response.json())
        .then(data => {
            // ...existing code...
        })
        .catch(error => {
            // ...existing code...
        });
};

// Global functions for loading home page content sections

// Make displaySearchResults globally accessible for all views
function displaySearchResults(tracks) {
    console.log('Displaying tracks:', tracks);
    const searchResults = document.getElementById('search-results');
    
    if (!searchResults) {
        console.error('search-results element not found');
        return;
    }
    
    searchResults.innerHTML = '';
    
    if (!Array.isArray(tracks) || tracks.length === 0) {
        searchResults.innerHTML = '<div class="empty-state"><h3>No tracks found</h3><p>Try another search or add more music to your library.</p></div>';
        return;
    }
    
    const resultsContainer = document.createElement('div');
    resultsContainer.className = 'track-grid';
    
    tracks.forEach(track => {
        const trackCard = createTrackCard(track);
        resultsContainer.appendChild(trackCard);
    });
    
    searchResults.appendChild(resultsContainer);
}

// Create track card function
function createTrackCard(track) {
    const trackCard = document.createElement('div');
    trackCard.className = 'track-card';
    
    // Create album art container with image
    const albumArt = document.createElement('div');
    albumArt.className = 'album-art';
    
    const img = document.createElement('img');
    if (track.album_art_url) {
        img.src = track.album_art_url;
    } else {
        img.src = '/static/images/default-album-art.png';
    }
    img.alt = 'Album Art';
    img.onerror = function() {
        this.src = '/static/images/default-album-art.png';
    };
    
    const playOverlay = document.createElement('div');
    playOverlay.className = 'play-overlay';
    playOverlay.innerHTML = '<i class="play-icon">▶</i>';
    
    albumArt.appendChild(img);
    albumArt.appendChild(playOverlay);
    trackCard.appendChild(albumArt);
    
    // Create track info container
    const trackInfo = document.createElement('div');
    trackInfo.className = 'track-info';
    
    const trackTitle = document.createElement('div');
    trackTitle.className = 'track-title';
    trackTitle.textContent = track.title || 'Unknown Title';
    
    const trackArtist = document.createElement('div');
    trackArtist.className = 'track-artist';
    trackArtist.textContent = track.artist || 'Unknown Artist';
    
    trackInfo.appendChild(trackTitle);
    trackInfo.appendChild(trackArtist);
    trackCard.appendChild(trackInfo);
    
    // Create actions container with all buttons
    const trackActions = document.createElement('div');
    trackActions.className = 'track-actions';
    
    // Play button
    const playButton = document.createElement('button');
    playButton.className = 'play-track';
    playButton.textContent = 'Play';
    playButton.dataset.id = track.id;
    playButton.addEventListener('click', function(e) {
        e.stopPropagation();
        window.playTrack(track.id);
    });
    
    // Station button
    const stationButton = document.createElement('button');
    stationButton.className = 'create-station';
    stationButton.textContent = 'Station';
    stationButton.dataset.id = track.id;
    stationButton.addEventListener('click', function(e) {
        e.stopPropagation();
        createStation(track.id);
    });
    
    // Like button
    const likeButton = document.createElement('button');
    likeButton.className = track.liked ? 'track-like-button liked' : 'track-like-button';
    likeButton.innerHTML = track.liked ? '♥' : '♡';
    likeButton.title = track.liked ? 'Unlike' : 'Like';
    likeButton.dataset.id = track.id;
    likeButton.addEventListener('click', function(e) {
        e.stopPropagation();
        toggleLikeStatus(track.id);
    });
    
    // Add all buttons to actions container
    trackActions.appendChild(playButton);
    trackActions.appendChild(stationButton);
    trackActions.appendChild(likeButton);
    
    trackCard.appendChild(trackActions);
    
    // Add click event to play track when clicking card
    trackCard.addEventListener('click', function() {
        window.playTrack(track.id);
    });
    
    return trackCard;
}

// Global explore loader - make sure it only updates the necessary elements
window.loadExplore = function() {
    console.log('Global loadExplore called');
    
    // Update heading
    const resultsHeading = document.getElementById('results-heading');
    if (resultsHeading) {
        resultsHeading.textContent = 'Discover';
    }
    
    const searchResults = document.getElementById('search-results');
    if (!searchResults) {
        console.error('search-results element not found');
        return;
    }
    
    // Show loading indicator
    searchResults.innerHTML = '<div class="loading">Loading tracks...</div>';
    
    // Hide the playlist container without recreating it
    const playlistContainer = document.getElementById('playlist-container');
    if (playlistContainer) {
        playlistContainer.style.display = 'none';
    }
    
    // Fetch explore data
    fetch('/explore')
        .then(response => response.json())
        .then(data => {
            console.log('Explore data received:', data);
            if (Array.isArray(data) && data.length > 0) {
                const displayData = data.slice(0, 12);
                displaySearchResults(displayData);
            } else if (Array.isArray(data) && data.length === 0) {
                searchResults.innerHTML = '<p>No tracks found. Try adding some music!</p>';
            } else if (data.error) {
                searchResults.innerHTML = `<p>Error: ${data.error}</p>`;
            }
        })
        .catch(error => {
            console.error('Error loading explore:', error);
            if (searchResults) {
                searchResults.innerHTML = '<p>Failed to load tracks. See console for details.</p>';
            }
        });
};

// Similarly update loadRecent and loadLiked to follow the same pattern
window.loadRecent = function() {
    console.log('Global loadRecent called');
    
    // Update heading
    const resultsHeading = document.getElementById('results-heading');
    if (resultsHeading) {
        resultsHeading.textContent = 'Recently Added';
    }
    
    const searchResults = document.getElementById('search-results');
    if (!searchResults) {
        console.error('search-results element not found');
        return;
    }
    
    // Show loading indicator
    searchResults.innerHTML = '<div class="loading">Loading recent tracks...</div>';
    
    // Hide the playlist container without recreating it
    const playlistContainer = document.getElementById('playlist-container');
    if (playlistContainer) {
        playlistContainer.style.display = 'none';
    }
    
    // Fetch recent tracks
    fetch('/recent')
        .then(response => response.json())
        .then(data => {
            console.log('Recent data received:', data);
            if (Array.isArray(data) && data.length > 0) {
                const displayData = data.slice(0, 12);
                displaySearchResults(displayData);
            } else if (Array.isArray(data) && data.length === 0) {
                searchResults.innerHTML = '<p>No recent tracks found. Try adding some music!</p>';
            } else if (data.error) {
                searchResults.innerHTML = `<p>Error: ${data.error}</p>`;
            }
        })
        .catch(error => {
            console.error('Error loading recent tracks:', error);
            if (searchResults) {
                searchResults.innerHTML = '<p>Failed to load recent tracks. See console for details.</p>';
            }
        });
};

window.loadLiked = function() {
    console.log('Global loadLiked called');
    
    // Update heading
    const resultsHeading = document.getElementById('results-heading');
    if (resultsHeading) {
        resultsHeading.textContent = 'Liked Tracks';
    }
    
    const searchResults = document.getElementById('search-results');
    if (!searchResults) {
        console.error('search-results element not found');
        return;
    }
    
    // Show loading indicator
    searchResults.innerHTML = '<div class="loading">Loading liked tracks...</div>';
    
    // Hide the playlist container without recreating it
    const playlistContainer = document.getElementById('playlist-container');
    if (playlistContainer) {
        playlistContainer.style.display = 'none';
    }
    
    // Fetch liked tracks
    fetch('/api/liked-tracks')
        .then(response => response.json())
        .then(data => {
            console.log('Liked tracks data received:', data);
            
            // Handle empty results
            if (!Array.isArray(data) || data.length === 0) {
                if (searchResults) {
                    searchResults.innerHTML = `
                        <div class="empty-state">
                            <h3>No liked tracks found</h3>
                            <p>Like some tracks to see them appear here.</p>
                        </div>
                    `;
                }
                return;
            }
            
            // Ensure all tracks have the liked property set to true
            const likedTracks = data.map(track => ({
                ...track,
                liked: true
            }));
            
            // Display the tracks
            displaySearchResults(likedTracks);
        })
        .catch(error => {
            console.error('Error loading liked tracks:', error);
            if (searchResults) {
                searchResults.innerHTML = `<div class="error">Error loading liked tracks: ${error}</div>`;
            }
        });
};

// Add helper function for like/unlike
function toggleLikeStatus(trackId) {
    if (!trackId) return;
    
    console.log('Toggling like status for track:', trackId);
    
    // Send request to toggle like status
    fetch(`/api/tracks/${trackId}/like`, {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        console.log('Like status toggled:', data);
        
        // Update the UI
        const likeButtons = document.querySelectorAll(`.track-like-button[data-id="${trackId}"]`);
        likeButtons.forEach(button => {
            if (data.liked) {
                button.classList.add('liked');
                button.innerHTML = '♥';
                button.title = 'Unlike';
            } else {
                button.classList.remove('liked');
                button.innerHTML = '♡';
                button.title = 'Like';
            }
        });
    })
    .catch(error => {
        console.error('Error toggling like status:', error);
    });
}

// Add create station function
function createStation(trackId) {
    if (!trackId) return;
    
    console.log('Creating station for track ID:', trackId);
    
    // Show the playlist container if it exists
    const playlistContainer = document.getElementById('playlist-container');
    if (playlistContainer) {
        playlistContainer.style.display = 'block';
    }
    
    // Show loading state in the playlist
    const playlist = document.getElementById('playlist');
    if (playlist) {
        playlist.innerHTML = '<div class="loading">Creating station based on this track...</div>';
    }
    
    // Get configured station size from settings if available
    const stationSize = window.stationSize || 20; // Default to 20 if not set
    
    // Fetch station tracks from the CORRECT endpoint "/station/[id]"
    fetch(`/station/${trackId}?num_tracks=${stationSize}`)
        .then(response => {
            console.log('Station response received:', response.status);
            if (!response.ok) {
                throw new Error(`Server returned ${response.status}: ${response.statusText}`);
            }
            return response.json();
        })
        .then(data => {
            console.log('Station data received:', data);
            if (Array.isArray(data) && data.length > 0) {
                // Store tracks in currentPlaylist
                window.currentPlaylist = data;
                
                // Display the tracks in the playlist
                displayPlaylist(data);
                
                // Update playlist header with seed track information
                const seedTrack = data[0];
                const playlistHeader = document.querySelector('.playlist-header h2');
                if (playlistHeader) {
                    playlistHeader.textContent = `Station: ${seedTrack.artist || 'Unknown'} - ${seedTrack.title || 'Unknown'} (${data.length} tracks)`;
                }
                
                // Enable save playlist button
                const savePlaylistBtn = document.getElementById('save-playlist-btn');
                if (savePlaylistBtn) {
                    savePlaylistBtn.disabled = false;
                }
            } else if (data.error) {
                // Show error message
                if (playlist) {
                    playlist.innerHTML = `<div class="error">Error creating station: ${data.error}</div>`;
                }
            } else {
                // Empty array but no error
                if (playlist) {
                    playlist.innerHTML = '<div class="empty-state">Could not create station. No similar tracks found.</div>';
                }
            }
        })
        .catch(error => {
            console.error('Error creating station:', error);
            if (playlist) {
                playlist.innerHTML = `<div class="error">Failed to create station: ${error.message}</div>`;
            }
        });
}

// Initialize player page
window.initPlayerPage = function() {
    const urlParams = new URLSearchParams(window.location.search);
    const view = urlParams.get('view');
    
    console.log('Initializing player page with view:', view);
    
    // Load the appropriate view based on URL parameter
    if (view === 'explore') {
        window.loadExplore();
    } else if (view === 'recent') {
        window.loadRecent();
    } else if (view === 'liked') {
        window.loadLiked();
    } else {
        // Default view - home shows explore
        window.loadExplore();
    }
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    window.initPlayerPage();
    
    // Search functionality
    const searchInput = document.getElementById('search-input');
    const searchButton = document.getElementById('search-button');
    
    if (searchButton && searchInput) {
        searchButton.addEventListener('click', function() {
            const query = searchInput.value.trim();
            if (query) {
                searchTracks(query);
            }
        });
        
        searchInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                const query = searchInput.value.trim();
                if (query) {
                    searchTracks(query);
                }
            }
        });
    }
    
    function searchTracks(query) {
        const searchResults = document.getElementById('search-results');
        const resultsHeading = document.getElementById('results-heading');
        
        if (resultsHeading) {
            resultsHeading.textContent = `Search Results: "${query}"`;
        }
        
        if (searchResults) {
            searchResults.innerHTML = '<div class="loading">Searching...</div>';
        }
        
        fetch(`/search?query=${encodeURIComponent(query)}`)
            .then(response => response.json())
            .then(data => {
                if (Array.isArray(data)) {
                    displaySearchResults(data);
                } else if (data.error) {
                    searchResults.innerHTML = `<p>Error: ${data.error}</p>`;
                }
            })
            .catch(error => {
                console.error('Error searching:', error);
                if (searchResults) {
                    searchResults.innerHTML = '<p>Search failed. See console for details.</p>';
                }
            });
    }
});

// Add this function to handle saving playlists
function saveCurrentPlaylist() {
    // Check if we have a playlist to save
    if (!window.currentPlaylist || window.currentPlaylist.length === 0) {
        alert('No playlist to save');
        return;
    }
    
    // Show the save playlist modal
    const savePlaylistModal = document.getElementById('save-playlist-modal');
    if (savePlaylistModal) {
        savePlaylistModal.style.display = 'block';
        
        // Set up the form submission
        const savePlaylistForm = document.getElementById('save-playlist-form');
        
        // Remove any previous event listeners
        const newForm = savePlaylistForm.cloneNode(true);
        savePlaylistForm.parentNode.replaceChild(newForm, savePlaylistForm);
        
        // Get fresh references to the NEW form elements after replacement
        const playlistNameInput = document.getElementById('playlist-name');
        const playlistDescriptionInput = document.getElementById('playlist-description');
        
        // Add new event listener
        newForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const name = playlistNameInput.value.trim();
            const description = playlistDescriptionInput.value.trim();
            
            if (!name) {
                alert('Please enter a playlist name');
                return;
            }
            
            // Get track IDs from the current playlist
            const trackIds = window.currentPlaylist.map(track => track.id);
            
            // Send request to save playlist
            fetch('/playlists', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    name: name,
                    description: description,
                    tracks: trackIds
                })
            })
            .then(response => response.json())
            .then(data => {
                console.log('Playlist saved:', data);
                
                // Show success message
                alert(`Playlist "${name}" saved successfully!`);
                
                // Hide the modal
                savePlaylistModal.style.display = 'none';
                
                // Reset form
                playlistNameInput.value = '';
                if (playlistDescriptionInput) {
                    playlistDescriptionInput.value = '';
                }
                
                // Refresh the playlists in sidebar
                if (typeof window.loadSidebarPlaylists === 'function') {
                    window.loadSidebarPlaylists();
                }
            })
            .catch(error => {
                console.error('Error saving playlist:', error);
                alert(`Error saving playlist: ${error.message}`);
            });
        });
    } else {
        alert('Save playlist modal not found');
    }
}

// Connect the Close button in the modal
document.addEventListener('DOMContentLoaded', function() {
    const closeButtons = document.querySelectorAll('.modal .close');
    
    closeButtons.forEach(button => {
        button.addEventListener('click', function() {
            const modal = this.closest('.modal');
            if (modal) {
                modal.style.display = 'none';
            }
        });
    });
    
    // Close modal when clicking outside of it
    window.addEventListener('click', function(e) {
        if (e.target.classList.contains('modal')) {
            e.target.style.display = 'none';
        }
    });
    
    // Connect Save Playlist button to the save function
    const savePlaylistBtn = document.getElementById('save-playlist-btn');
    if (savePlaylistBtn) {
        savePlaylistBtn.addEventListener('click', function() {
            saveCurrentPlaylist();
        });
    }
});

// Add this to your static/js/player.js file
document.addEventListener('DOMContentLoaded', function() {
    // Connect Play All button
    const playAllBtn = document.getElementById('play-all-btn');
    if (playAllBtn) {
        playAllBtn.addEventListener('click', function() {
            if (!window.currentPlaylist || window.currentPlaylist.length === 0) {
                alert('No tracks to play');
                return;
            }
            
            console.log(`Playing all ${window.currentPlaylist.length} tracks in playlist`);
            
            // Use the existing playEntirePlaylist function if available
            if (typeof window.playEntirePlaylist === 'function') {
                window.playEntirePlaylist(window.currentPlaylist);
            } else {
                // Fallback: Just play the first track
                if (window.currentPlaylist[0] && typeof window.playTrack === 'function') {
                    window.playTrack(window.currentPlaylist[0].id);
                }
            }
        });
    }
});