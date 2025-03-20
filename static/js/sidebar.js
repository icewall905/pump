// Common sidebar functionality for all pages

document.addEventListener('DOMContentLoaded', function() {
    // Load playlists for sidebar
    const playlistList = document.querySelector('.playlist-list');
    
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
        playlistList.innerHTML = '<div class="loading">Loading playlists...</div>';
        
        fetch('/playlists')
            .then(response => response.json())
            .then(data => {
                console.log('Playlists data:', data);
                
                if (!Array.isArray(data)) {
                    if (data.error) {
                        playlistList.innerHTML = `<div class="error">Error: ${data.error}</div>`;
                    } else {
                        playlistList.innerHTML = '<div class="error">Invalid response</div>';
                    }
                    return;
                }
                
                if (data.length === 0) {
                    playlistList.innerHTML = '<div class="empty">No saved playlists</div>';
                    return;
                }
                
                // Display playlists
                playlistList.innerHTML = '';
                
                data.forEach(playlist => {
                    const div = document.createElement('div');
                    div.className = 'playlist-item';
                    div.innerHTML = `
                        <div class="playlist-name">${playlist.name}
                            <span class="playlist-count">(${playlist.track_count})</span>
                        </div>
                        <div class="playlist-actions">
                            <button class="load-playlist" data-id="${playlist.id}">Load</button>
                            <button class="delete-playlist" data-id="${playlist.id}">×</button>
                        </div>
                    `;
                    playlistList.appendChild(div);
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
                playlistList.innerHTML = '<div class="error">Failed to load playlists</div>';
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

    loadPlaylists();
});

function initSidebarMetadataProgress() {
    function checkStatus() {
        fetch('/api/metadata-update/status')
            .then(r => r.json())
            .then(status => {
                const container = document.getElementById('metadata-sidebar-progress');
                if (!container) return;
                const fill = container.querySelector('.progress-fill');
                const text = container.querySelector('.progress-status-text');
                
                if (status.running) {
                    container.style.display = 'block';
                    fill.style.width = `${status.percent_complete}%`;
                    text.textContent = `Metadata Update: ${status.processed_tracks}/${status.total_tracks} (${status.percent_complete}%)`;
                } else {
                    container.style.display = 'none';
                    fill.style.width = '0%';
                    text.textContent = 'Metadata update idle';
                }
            })
            .catch(err => console.error('Sidebar metadata status error:', err))
            .finally(() => setTimeout(checkStatus, 2000));
    }
    checkStatus();
}
document.addEventListener('DOMContentLoaded', initSidebarMetadataProgress);