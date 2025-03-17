// Simple version focused on loading tracks

// Track current playlist
let currentPlaylist = [];

document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM loaded - initializing player.js');
    
    // DOM elements
    const searchInput = document.getElementById('search-input');
    const searchButton = document.getElementById('search-button');
    const searchResults = document.getElementById('search-results');
    const playlist = document.getElementById('playlist');
    const exploreLink = document.getElementById('explore-link');
    const recentLink = document.getElementById('recent-link');
    const resultsContainer = document.querySelector('.results-container');
    const savePlaylistBtn = document.getElementById('save-playlist-btn');
    const analyzeStatus = document.getElementById('analyze-status');  // ADD THIS LINE
    
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
            console.log('Explore link clicked');
            loadExplore();
        });
    }
    
    if (recentLink) {
        recentLink.addEventListener('click', function(e) {
            e.preventDefault();
            console.log('Recent link clicked');
            loadRecent();
        });
    }
    
    // Load explore on page load
    console.log('Loading explore by default');
    loadExplore();
    
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
                    displaySearchResults(data);
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
                    displaySearchResults(data);
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
            const trackCard = document.createElement('div');
            trackCard.className = 'track-card';
            
            const artDiv = document.createElement('div');
            artDiv.className = 'track-art';
            
            // Add album art if available, otherwise show placeholder
            if (track.album_art_url) {
                const img = document.createElement('img');
                const imgUrl = track.album_art_url.startsWith('http') ? 
                    `/albumart/${encodeURIComponent(track.album_art_url)}` : track.album_art_url;
                
                img.src = imgUrl;
                img.alt = track.album || track.title;
                img.onerror = function() {
                    console.log('Image failed to load:', imgUrl);
                    this.style.display = 'none';
                    artDiv.classList.add('default-art');
                    const placeholder = document.createElement('div');
                    placeholder.className = 'art-placeholder';
                    placeholder.textContent = (track.artist && track.artist !== 'Unknown') ? 
                        track.artist.charAt(0).toUpperCase() : 
                        (track.title ? track.title.charAt(0).toUpperCase() : '?');
                    artDiv.appendChild(placeholder);
                };
                artDiv.appendChild(img);
            } else {
                console.log('No album art for track:', track.title);
                // No album art URL, use placeholder
                artDiv.classList.add('default-art');
                const placeholder = document.createElement('div');
                placeholder.className = 'art-placeholder';
                placeholder.textContent = (track.artist && track.artist !== 'Unknown') ? 
                    track.artist.charAt(0).toUpperCase() : 
                    (track.title ? track.title.charAt(0).toUpperCase() : '?');
                artDiv.appendChild(placeholder);
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
                <button class="play-track" data-id="${track.id}">Play</button>
                <button class="create-station" data-id="${track.id}">Create Station</button>
            `;
            
            trackCard.appendChild(artDiv);
            trackCard.appendChild(infoDiv);
            trackCard.appendChild(actionsDiv);
            
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
                // Implement play functionality
            });
        });
    }
    
    // Update the createStation function to actually display the playlist
    function createStation(trackId) {
        if (analyzeStatus) {
            showAnalyzeStatus('Creating playlist...', 'progress');
        }
        
        // Add this line to show loading in the playlist area too
        const playlistContainer = document.getElementById('playlist');
        if (playlistContainer) {
            playlistContainer.innerHTML = '<div class="loading-large">Analyzing music and building playlist based on this track...</div>';
        }
        
        fetch(`/playlist?seed_track_id=${trackId}`)
            .then(response => response.json())
            .then(data => {
                console.log('Playlist data:', data);
                if (Array.isArray(data)) {
                    // Store current playlist
                    currentPlaylist = data;
                    
                    // Display the playlist
                    displayPlaylist(data);
                    
                    // Update header with seed track info
                    const seedTrack = data.find(t => t.id == trackId) || {};
                    const playlistHeader = document.querySelector('.playlist-container h2');
                    if (playlistHeader) {
                        playlistHeader.textContent = `Station: ${seedTrack.artist || 'Unknown'} - ${seedTrack.title || 'Unknown'}`;
                    }
                    
                    // Enable save button
                    if (savePlaylistBtn) {
                        savePlaylistBtn.disabled = false;
                    }
                    
                    // Clear status
                    if (analyzeStatus) {
                        analyzeStatus.innerHTML = '';
                    }
                } else if (data.error) {
                    if (analyzeStatus) {
                        showAnalyzeStatus(`Error: ${data.error}`, 'error');
                    }
                } else {
                    if (analyzeStatus) {
                        showAnalyzeStatus('Invalid response from server', 'error');
                    }
                }
            })
            .catch(error => {
                console.error('Error creating station:', error);
                if (analyzeStatus) {
                    showAnalyzeStatus('Failed to create playlist', 'error');
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
        console.log('Loading playlists...');
        const playlistList = document.getElementById('playlist-list');
        
        if (!playlistList) {
            console.error('Playlist list element not found');
            return;
        }
        
        playlistList.innerHTML = '<li class="loading">Loading playlists...</li>';
        
        fetch('/playlists')
            .then(response => {
                console.log('Playlists response:', response);
                return response.json();
            })
            .then(data => {
                console.log('Playlists data:', data);
                
                if (!Array.isArray(data)) {
                    if (data.error) {
                        playlistList.innerHTML = `<li class="error">Error: ${data.error}</li>`;
                    } else {
                        playlistList.innerHTML = '<li class="error">Invalid response</li>';
                    }
                    return;
                }
                
                if (data.length === 0) {
                    playlistList.innerHTML = '<li class="empty">No saved playlists</li>';
                    return;
                }
                
                // Display playlists
                playlistList.innerHTML = '';
                
                data.forEach(playlist => {
                    const li = document.createElement('li');
                    li.className = 'playlist-item';
                    li.innerHTML = `
                        <div class="playlist-name">${playlist.name}
                            <span class="playlist-count">(${playlist.track_count})</span>
                        </div>
                        <div class="playlist-actions">
                            <button class="load-playlist" data-id="${playlist.id}">Load</button>
                            <button class="delete-playlist" data-id="${playlist.id}">×</button>
                        </div>
                    `;
                    playlistList.appendChild(li);
                });
                
                // Add event listeners to buttons
                document.querySelectorAll('.load-playlist').forEach(btn => {
                    btn.addEventListener('click', function() {
                        loadPlaylist(this.dataset.id);
                    });
                });
                
                document.querySelectorAll('.delete-playlist').forEach(btn => {
                    btn.addEventListener('click', function() {
                        if (confirm('Are you sure you want to delete this playlist?')) {
                            deletePlaylist(this.dataset.id);
                        }
                    });
                });
            })
            .catch(error => {
                console.error('Error loading playlists:', error);
                playlistList.innerHTML = '<li class="error">Failed to load playlists</li>';
            });
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
        
        if (!currentPlaylist || currentPlaylist.length === 0) {
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
        const trackIds = currentPlaylist.map(track => track.id);
        
        // Save to server
        console.log('Saving playlist:', { name, description, tracks: trackIds });
        
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
            console.log('Save playlist response:', data);
            
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
                
                // Show success message
                showAnalyzeStatus(`Playlist "${name}" saved successfully`, 'success');
                
                // Refresh playlist list
                loadPlaylists();
            }
        })
        .catch(error => {
            console.error('Error saving playlist:', error);
            alert('Failed to save playlist');
        });
    }
    
    // Expose the inner savePlaylist function to the window for any direct HTML onclick references
    window.savePlaylist = savePlaylist;
});

// Remove the global savePlaylist function if it exists
// function savePlaylist() { ... } - DELETE THIS ENTIRE FUNCTION