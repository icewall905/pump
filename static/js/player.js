document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('search-input');
    const searchButton = document.getElementById('search-button');
    const searchResults = document.getElementById('search-results');
    const playlist = document.getElementById('playlist');
    const exploreLink = document.getElementById('explore-link');
    const analyzeForm = document.getElementById('analyze-form');
    const analyzeStatus = document.getElementById('analyze-status');
    
    // Search functionality
    searchButton.addEventListener('click', function() {
        const query = searchInput.value.trim();
        if (query) {
            searchTracks(query);
        }
    });
    
    // Enter key in search input
    searchInput.addEventListener('keyup', function(event) {
        if (event.key === 'Enter') {
            const query = searchInput.value.trim();
            if (query) {
                searchTracks(query);
            }
        }
    });
    
    // Explore link
    exploreLink.addEventListener('click', function(e) {
        e.preventDefault();
        exploreMusic();
    });
    
    // Analyze form submission
    analyzeForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const folderPath = document.getElementById('folder-path').value.trim();
        if (!folderPath) {
            showAnalyzeStatus('Please enter a folder path', 'error');
            return;
        }
        
        const recursive = document.getElementById('recursive').checked;
        
        analyzeMusic(folderPath, recursive);
    });
    
    function searchTracks(query) {
        showAnalyzeStatus('Searching...', 'progress');
        
        fetch(`/search?query=${encodeURIComponent(query)}`)
            .then(response => response.json())
            .then(data => {
                displaySearchResults(data);
                analyzeStatus.innerHTML = '';
            })
            .catch(error => {
                console.error('Error searching tracks:', error);
                searchResults.innerHTML = '<p>Error searching tracks. Please try again.</p>';
                showAnalyzeStatus('Search failed', 'error');
            });
    }
    
    function exploreMusic() {
        showAnalyzeStatus('Loading random tracks...', 'progress');
        
        fetch('/explore')
            .then(response => response.json())
            .then(data => {
                displaySearchResults(data);
                analyzeStatus.innerHTML = '';
            })
            .catch(error => {
                console.error('Error exploring tracks:', error);
                searchResults.innerHTML = '<p>Error loading random tracks. Please try again.</p>';
                showAnalyzeStatus('Failed to load tracks', 'error');
            });
    }
    
    function analyzeMusic(folderPath, recursive) {
        showAnalyzeStatus('Analyzing music folder...', 'progress');
        
        const formData = new FormData();
        formData.append('folder_path', folderPath);
        formData.append('recursive', recursive);
        
        fetch('/analyze', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                showAnalyzeStatus(`Error: ${data.error}`, 'error');
            } else {
                showAnalyzeStatus(`Successfully analyzed ${data.files_processed} files. Found ${data.tracks_added} tracks.`, 'success');
            }
        })
        .catch(error => {
            console.error('Error analyzing music:', error);
            showAnalyzeStatus('Failed to analyze folder', 'error');
        });
    }
    
    function showAnalyzeStatus(message, type) {
        analyzeStatus.textContent = message;
        analyzeStatus.className = '';
        analyzeStatus.classList.add(`status-${type}`);
    }
    
    function displaySearchResults(tracks) {
        // Add debugging
        console.log("Tracks data:", tracks);
        
        searchResults.innerHTML = '';
        
        if (tracks.length === 0) {
            searchResults.innerHTML = '<p>No tracks found.</p>';
            return;
        }
        
        const resultsContainer = document.createElement('div');
        resultsContainer.className = 'track-grid';
        
        tracks.forEach(track => {
            const trackCard = document.createElement('div');
            trackCard.className = 'track-card';
            
            const artDiv = document.createElement('div');
            artDiv.className = 'track-art';
            
            // Add album art if available, otherwise show placeholder
            if (track.album_art_url) {
                // Use the proxy for external URLs
                const imgUrl = track.album_art_url.startsWith('http') ? 
                    `/albumart/${encodeURIComponent(track.album_art_url)}` : track.album_art_url;
                    
                console.log(`Track ${track.id} using image URL: ${imgUrl}`);
                const img = document.createElement('img');
                img.src = imgUrl;
                img.alt = track.album || track.title;
                // Add onerror debugging
                img.onerror = function() {
                    console.error(`Failed to load image: ${track.album_art_url}`);
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
                console.log(`Track ${track.id} has no album art URL`);
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
                createStation(this.dataset.id);
            });
        });
        
        document.querySelectorAll('.play-track').forEach(button => {
            button.addEventListener('click', function() {
                // Implement play functionality
                console.log(`Play track ${this.dataset.id}`);
            });
        });
    }
    
    function createStation(trackId) {
        showAnalyzeStatus('Creating playlist...', 'progress');
        
        fetch(`/playlist?seed_track_id=${trackId}`)
            .then(response => response.json())
            .then(data => {
                displayPlaylist(data);
                analyzeStatus.innerHTML = '';
            })
            .catch(error => {
                console.error('Error creating station:', error);
                playlist.innerHTML = '<p>Error creating station. Please try again.</p>';
                showAnalyzeStatus('Failed to create playlist', 'error');
            });
    }
    
    function displayPlaylist(tracks) {
        playlist.innerHTML = '';
        
        if (!Array.isArray(tracks)) {
            if (tracks.error) {
                playlist.innerHTML = `<p>Error: ${tracks.error}</p>`;
            } else {
                playlist.innerHTML = '<p>Failed to create playlist.</p>';
            }
            return;
        }
        
        if (tracks.length === 0) {
            playlist.innerHTML = '<p>No tracks in playlist.</p>';
            return;
        }
        
        const playlistContainer = document.createElement('div');
        playlistContainer.className = 'track-grid';
        
        tracks.forEach(track => {
            const trackCard = document.createElement('div');
            trackCard.className = 'track-card';
            
            const artDiv = document.createElement('div');
            artDiv.className = 'track-art';
            
            // Add album art if available, otherwise show placeholder
            if (track.album_art_url) {
                const img = document.createElement('img');
                img.src = track.album_art_url;
                img.alt = track.album || track.title;
                img.onerror = function() {
                    // If image fails to load, replace with placeholder
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
            
            const playButton = document.createElement('div');
            playButton.className = 'track-actions';
            playButton.innerHTML = '<button class="play-track" data-id="' + track.id + '">Play</button>';
            
            trackCard.appendChild(artDiv);
            trackCard.appendChild(infoDiv);
            trackCard.appendChild(playButton);
            
            playlistContainer.appendChild(trackCard);
        });
        
        playlist.appendChild(playlistContainer);
        
        // Add event listeners
        document.querySelectorAll('.play-track').forEach(button => {
            button.addEventListener('click', function() {
                // Implement play functionality
                console.log(`Play track ${this.dataset.id}`);
            });
        });
    }
});