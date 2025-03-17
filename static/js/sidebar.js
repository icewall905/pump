// Common sidebar functionality for all pages

document.addEventListener('DOMContentLoaded', function() {
    // Load playlists for sidebar
    const playlistList = document.getElementById('playlist-list');
    
    if (playlistList) {
        loadPlaylists();
    }
    
    function loadPlaylists() {
        console.log('Loading playlists for sidebar...');
        
        if (!playlistList) {
            console.error('Playlist list element not found');
            return;
        }
        
        // Show loading indicator
        playlistList.innerHTML = '<li class="loading">Loading playlists...</li>';
        
        fetch('/playlists')
            .then(response => response.json())
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
                        if (typeof loadPlaylist === 'function') {
                            loadPlaylist(this.dataset.id);
                        } else {
                            // If on settings page or other page without loadPlaylist function
                            window.location.href = `/?playlist=${this.dataset.id}`;
                        }
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
    
    // Make functions available globally if needed
    window.loadSidebarPlaylists = loadPlaylists;
});