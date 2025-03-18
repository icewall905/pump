document.addEventListener('DOMContentLoaded', function() {
    // Get DOM elements
    const tabArtists = document.getElementById('tab-artists');
    const tabAlbums = document.getElementById('tab-albums');
    const tabSongs = document.getElementById('tab-songs');
    const libraryContent = document.getElementById('library-content');
    const searchInput = document.getElementById('library-search-input');
    const searchClear = document.getElementById('library-search-clear');
    
    let currentTab = 'artists';
    let currentData = [];
    let filteredData = [];
    
    // Initialize
    loadArtists();
    
    // Event listeners for tabs
    tabArtists.addEventListener('click', function() {
        setActiveTab('artists');
        loadArtists();
    });
    
    tabAlbums.addEventListener('click', function() {
        setActiveTab('albums');
        loadAlbums();
    });
    
    tabSongs.addEventListener('click', function() {
        setActiveTab('songs');
        loadSongs();
    });
    
    // Search functionality
    searchInput.addEventListener('input', function() {
        filterContent(this.value);
    });
    
    searchClear.addEventListener('click', function() {
        searchInput.value = '';
        filterContent('');
    });
    
    function setActiveTab(tab) {
        currentTab = tab;
        
        // Remove active class from all tabs
        tabArtists.classList.remove('active');
        tabAlbums.classList.remove('active');
        tabSongs.classList.remove('active');
        
        // Add active class to selected tab
        if (tab === 'artists') {
            tabArtists.classList.add('active');
        } else if (tab === 'albums') {
            tabAlbums.classList.add('active');
        } else if (tab === 'songs') {
            tabSongs.classList.add('active');
        }
    }
    
    function loadArtists() {
        showLoading();
        
        fetch('/api/library/artists')
            .then(response => response.json())
            .then(data => {
                currentData = data;
                filterContent(searchInput.value);
            })
            .catch(error => {
                console.error('Error loading artists:', error);
                libraryContent.innerHTML = `<div class="error">Failed to load artists. ${error.message}</div>`;
            });
    }
    
    function loadAlbums() {
        showLoading();
        
        fetch('/api/library/albums')
            .then(response => response.json())
            .then(data => {
                currentData = data;
                filterContent(searchInput.value);
            })
            .catch(error => {
                console.error('Error loading albums:', error);
                libraryContent.innerHTML = `<div class="error">Failed to load albums. ${error.message}</div>`;
            });
    }
    
    function loadSongs() {
        showLoading();
        
        fetch('/api/library/songs')
            .then(response => response.json())
            .then(data => {
                console.log('Songs data received:', data);
                
                // Make sure data is an array
                if (!Array.isArray(data)) {
                    console.error('Expected array but got:', typeof data);
                    if (data.error) {
                        libraryContent.innerHTML = `<div class="error">Error: ${data.error}</div>`;
                    } else {
                        // Convert to array if possible or use empty array
                        currentData = Array.isArray(data.songs) ? data.songs : [];
                        if (!Array.isArray(currentData)) {
                            currentData = [];
                        }
                    }
                } else {
                    currentData = data;
                }
                
                filterContent(searchInput.value);
            })
            .catch(error => {
                console.error('Error loading songs:', error);
                libraryContent.innerHTML = `<div class="error">Failed to load songs. ${error.message}</div>`;
            });
    }
    
    function filterContent(query) {
        query = query.toLowerCase();
        
        if (query === '') {
            filteredData = currentData;
        } else {
            if (currentTab === 'artists') {
                filteredData = currentData.filter(artist => 
                    artist.artist.toLowerCase().includes(query)
                );
            } else if (currentTab === 'albums') {
                filteredData = currentData.filter(album => 
                    album.album.toLowerCase().includes(query) || 
                    album.artist.toLowerCase().includes(query)
                );
            } else if (currentTab === 'songs') {
                filteredData = currentData.filter(song => 
                    (song.title && song.title.toLowerCase().includes(query)) || 
                    (song.artist && song.artist.toLowerCase().includes(query)) || 
                    (song.album && song.album.toLowerCase().includes(query))
                );
            }
        }
        
        renderContent();
    }
    
    function renderContent() {
        if (filteredData.length === 0) {
            libraryContent.innerHTML = `<div class="empty-library">No ${currentTab} found</div>`;
            return;
        }
        
        if (currentTab === 'artists') {
            renderArtists(filteredData);
        } else if (currentTab === 'albums') {
            renderAlbums();
        } else if (currentTab === 'songs') {
            renderSongs();
        }
    }
    
    function renderArtists(artists) {
        const container = document.getElementById('library-content');
        container.innerHTML = '<div class="library-grid" id="artists-grid"></div>';
        const grid = document.getElementById('artists-grid');
        
        artists.forEach(artist => {
            // Create artist element
            const artistEl = document.createElement('div');
            artistEl.className = 'artist-item';
            
            // Handle the artist image URL correctly
            let imageUrl = '/static/images/default-artist-image.png'; // Default image
            
            if (artist.artist_image_url && artist.artist_image_url !== '') {
                // Use the proxy for the artist image URL (not album art!)
                imageUrl = '/artistimg/' + encodeURIComponent(artist.artist_image_url);
            }
            
            // Render the artist with proper image
            artistEl.innerHTML = `
                <div class="artist-image">
                    <img src="${imageUrl}" alt="${artist.artist}" onerror="this.src='/static/images/default-artist-image.png';">
                </div>
                <div class="artist-details">
                    <h3>${artist.artist}</h3>
                    <p>${artist.track_count} track${artist.track_count !== 1 ? 's' : ''}</p>
                </div>
            `;
            
            // Add click handler to show artist's tracks
            artistEl.addEventListener('click', () => {
                // Navigate to artist page or filter tracks by artist
                console.log(`Artist clicked: ${artist.artist}`);
            });
            
            grid.appendChild(artistEl);
        });
    }
    
    function renderAlbums() {
        let html = '<div class="library-grid">';
        
        filteredData.forEach(album => {
            const albumArt = album.album_art_url ? 
                `<img src="${escapeHtml(album.album_art_url)}" alt="${escapeHtml(album.album)}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                 <div class="art-placeholder" style="display:none;">💿</div>` : 
                '<div class="art-placeholder">💿</div>';
            
            html += `
                <div class="library-item album-item" data-album="${escapeHtml(album.album)}" data-artist="${escapeHtml(album.artist)}">
                    <div class="album-art">
                        ${albumArt}
                    </div>
                    <div class="album-info">
                        <div class="album-name">${escapeHtml(album.album)}</div>
                        <div class="album-artist">${escapeHtml(album.artist)}</div>
                        <div class="album-count">${album.track_count} tracks</div>
                    </div>
                </div>
            `;
        });
        
        html += '</div>';
        libraryContent.innerHTML = html;
        
        // Add event listeners to album items
        document.querySelectorAll('.album-item').forEach(item => {
            item.addEventListener('click', function() {
                const album = this.getAttribute('data-album');
                const artist = this.getAttribute('data-artist');
                playSample(currentData.find(a => a.album === album && a.artist === artist).sample_track);
            });
        });
    }
    
    function renderSongs() {
        let html = `
            <div class="tracks-container">
                <table class="tracks-table">
                    <thead>
                        <tr>
                            <th width="60"></th>
                            <th>Title</th>
                            <th>Artist</th>
                            <th>Album</th>
                            <th width="80" class="track-duration">Duration</th>
                        </tr>
                    </thead>
                    <tbody>
        `;
        
        filteredData.forEach(track => {
            const title = track.title || 'Unknown Title';
            const artist = track.artist || 'Unknown Artist';
            const album = track.album || 'Unknown Album';
            
            // Format duration
            let duration = '';
            if (track.duration) {
                const minutes = Math.floor(track.duration / 60);
                const seconds = Math.floor(track.duration % 60);
                duration = `${minutes}:${seconds.toString().padStart(2, '0')}`;
            }
            
            html += `
                <tr class="track-row" data-file-path="${escapeHtml(track.file_path)}">
                    <td class="track-play">
                        <button class="play-button">▶</button>
                    </td>
                    <td>${escapeHtml(title)}</td>
                    <td>${escapeHtml(artist)}</td>
                    <td>${escapeHtml(album)}</td>
                    <td class="track-duration">${duration}</td>
                </tr>
            `;
        });
        
        html += `
                    </tbody>
                </table>
            </div>
        `;
        
        libraryContent.innerHTML = html;
        
        // Add event listeners to play buttons
        document.querySelectorAll('.play-button').forEach(button => {
            button.addEventListener('click', function(e) {
                e.stopPropagation();
                const trackRow = this.closest('.track-row');
                const filePath = trackRow.getAttribute('data-file-path');
                playSample(filePath);
            });
        });
        
        // Add event listeners to track rows
        document.querySelectorAll('.track-row').forEach(row => {
            row.addEventListener('click', function() {
                const filePath = this.getAttribute('data-file-path');
                playSample(filePath);
            });
        });
    }
    
    function showLoading() {
        libraryContent.innerHTML = '<div class="loading-large">Loading library...</div>';
    }
    
    function playSample(filePath) {
        // Get the playerManager from app.js (global variable)
        if (window.playerManager) {
            window.playerManager.playTrack(filePath);
        } else {
            console.error('playerManager not available');
        }
    }
    
    // Helper function to escape HTML to prevent XSS
    function escapeHtml(str) {
        if (!str) return '';
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }
});