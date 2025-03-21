// Common sidebar functionality for all pages

document.addEventListener('DOMContentLoaded', function() {
    // Load playlists for sidebar
    const playlistList = document.querySelector('.playlist-list');
    
    if (playlistList) {
        loadPlaylists();
    }
    
    // Initialize sidebar progress indicators
    initSidebarAnalysisProgress();
    initSidebarMetadataProgress();
    
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

// Function to handle analysis progress in sidebar
function initSidebarAnalysisProgress() {
    console.log('Initializing sidebar analysis progress checker');
    
    function checkStatus() {
        fetch('/api/analysis/status')
            .then(r => r.json())
            .then(status => {
                console.log('Analysis status received:', status);
                const container = document.getElementById('analysis-sidebar-progress');
                if (!container) {
                    console.error('analysis-sidebar-progress container not found');
                    return;
                }
                
                const fill = container.querySelector('.progress-fill');
                const text = container.querySelector('.progress-status-text');
                
                if (!fill || !text) {
                    console.error('Progress fill or text elements not found');
                    return;
                }
                
                if (status.running) {
                    console.log('Analysis is running, showing progress');
                    container.style.display = 'block';
                    
                    // Get accurate data for display
                    const filesProcessed = status.files_processed || 0;
                    const totalFiles = status.total_files || 0;
                    const percent = status.percent_complete || 0;
                    
                    // Set width based on percentage
                    fill.style.width = `${percent}%`;
                    
                    // Display appropriate text based on scan_complete flag
                    if (!status.scan_complete) {
                        text.textContent = `Analysis: ${filesProcessed} files found`;
                    } else {
                        // For analysis phase - percent now goes from 0 to 100
                        const displayProcessed = Math.min(filesProcessed, totalFiles);
                        text.textContent = `Analyzing: ${displayProcessed} of ${totalFiles} files`;
                    }
                } else {
                    // Check if there's a completed message to show briefly
                    if (status.last_updated && !status.error) {
                        const lastUpdateTime = new Date(status.last_updated);
                        const now = new Date();
                        const secondsSinceUpdate = (now - lastUpdateTime) / 1000;
                        
                        // Show completion message for up to 5 seconds after completion
                        if (secondsSinceUpdate < 5) {
                            fill.style.width = '100%';
                            text.textContent = `Analysis complete: ${status.files_processed} files processed`;
                            container.style.display = 'block';
                        } else {
                            container.style.display = 'none';
                        }
                    } else {
                        container.style.display = 'none';
                    }
                }
            })
            .catch(err => {
                console.error('Sidebar analysis status error:', err);
            })
            .finally(() => {
                setTimeout(checkStatus, 2000);
            });
    }
    
    // Start checking
    checkStatus();
}

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

// Add this function if it doesn't already exist, or update it if it does

function initSidebarQuickScanProgress() {
    function checkStatus() {
        fetch('/api/quick-scan/status')
            .then(r => r.json())
            .then(status => {
                const container = document.getElementById('analysis-sidebar-progress');
                if (!container) return;
                
                const fill = container.querySelector('.progress-fill');
                const text = container.querySelector('.progress-status-text');
                
                if (status.running) {
                    container.style.display = 'block';
                    fill.style.width = `${status.percent_complete}%`;
                    text.textContent = `Quick scan: ${status.files_processed} files processed`;
                } else if (!document.getElementById('metadata-sidebar-progress').style.display === 'block') {
                    // Hide only if metadata update isn't also running
                    container.style.display = 'none';
                }
            })
            .catch(err => console.error('Sidebar quick scan status error:', err))
            .finally(() => setTimeout(checkStatus, 2000));
    }
    
    checkStatus();
}

// Call this function when document is ready
document.addEventListener('DOMContentLoaded', initSidebarQuickScanProgress);