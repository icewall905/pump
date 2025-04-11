// Sidebar functionality
document.addEventListener('DOMContentLoaded', function() {
    console.log('Initializing sidebar.js');
    
    // Global status indicator elements
    const analysisStatusIndicator = document.getElementById('analysis-sidebar-progress');
    const metadataStatusIndicator = document.getElementById('metadata-sidebar-progress');
    
    // Check if we found our status indicators
    if (analysisStatusIndicator) {
        console.log('Found analysis status indicator element');
    } else {
        console.error('Could not find analysis-sidebar-progress element');
    }
    
    if (metadataStatusIndicator) {
        console.log('Found metadata status indicator element');
    } else {
        console.error('Could not find metadata-sidebar-progress element');
    }
    
    // Initialize library stats
    updateLibraryStats();
    
    // Load playlists in sidebar
    window.loadSidebarPlaylists();
    
    // Check for status indicators and initialize status checking
    if (analysisStatusIndicator && metadataStatusIndicator) {
        console.log('Initializing status checking for sidebar indicators');
        initializeStatusChecking();
    }
    
    // Add event listeners for sidebar navigation elements
    initializeSidebarNavigation();
    
    // Make sure PlayerManager is initialized first before using it
    if (!window.playerManager && typeof PlayerManager === 'function') {
        console.log("Initializing PlayerManager from sidebar.js");
        window.playerManager = new PlayerManager();
    }
    
    function initializeStatusChecking() {
        // Check analysis status periodically
        function checkAnalysisStatus() {
            fetch('/api/analysis/status')
                .then(response => response.json())
                .then(data => {
                    console.log('Analysis status update:', data);
                    // Update UI with status - show progress if either running is true OR files are being processed
                    if (data.running || (data.files_processed > 0 && data.files_processed < data.total_files)) {
                        // Calculate percent complete - either use the API value or calculate it
                        let percentComplete = data.percent_complete;
                        if (!percentComplete && data.total_files > 0) {
                            percentComplete = Math.round((data.files_processed / data.total_files) * 100);
                        }
                        
                        // Make the indicator visible - force display with !important
                        analysisStatusIndicator.style.cssText = 'display: block !important; visibility: visible !important; opacity: 1 !important; background-color: rgba(0,0,0,0.3); padding: 10px; margin: 10px 0; border-radius: 4px;';
                        analysisStatusIndicator.classList.add('active');
                        analysisStatusIndicator.innerHTML = `
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${percentComplete}%; background-color: #4caf50;"></div>
                            </div>
                            <div class="progress-status-text" style="color: white; font-size: 12px; text-align: center; margin-top: 5px;">
                                Analyzing: ${data.files_processed}/${data.total_files} files (${percentComplete}%)
                            </div>
                        `;
                        console.log('Analysis progress shown:', percentComplete + '%');
                    } else {
                        analysisStatusIndicator.classList.remove('active');
                        analysisStatusIndicator.style.cssText = 'display: none;';
                        analysisStatusIndicator.innerHTML = `
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: 0%"></div>
                            </div>
                            <div class="progress-status-text">Analysis idle</div>
                        `;
                    }
                })
                .catch(error => {
                    console.error('Error fetching analysis status:', error);
                });
        }
        
        // Check metadata update status periodically
        function checkMetadataStatus() {
            fetch('/api/metadata-update/status')
                .then(response => response.json())
                .then(data => {
                    console.log('Metadata status update:', data);
                    if (data.running) {
                        // Make the indicator visible - force display with !important
                        metadataStatusIndicator.style.cssText = 'display: block !important; visibility: visible !important; opacity: 1 !important; background-color: rgba(0,0,0,0.3); padding: 10px; margin: 10px 0; border-radius: 4px;';
                        metadataStatusIndicator.classList.add('active');
                        metadataStatusIndicator.innerHTML = `
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${data.percent_complete}%; background-color: #4caf50;"></div>
                            </div>
                            <div class="progress-status-text" style="color: white; font-size: 12px; text-align: center; margin-top: 5px;">
                                Updating metadata: ${data.percent_complete}% complete
                            </div>
                        `;
                        console.log('Metadata progress shown:', data.percent_complete + '%');
                    } else {
                        metadataStatusIndicator.classList.remove('active');
                        metadataStatusIndicator.style.cssText = 'display: none;';
                        metadataStatusIndicator.innerHTML = `
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: 0%"></div>
                            </div>
                            <div class="progress-status-text"></div>
                        `;
                    }
                })
                .catch(error => {
                    console.error('Error fetching metadata status:', error);
                });
        }
        
        // Set up status checking intervals
        const analysisStatusInterval = setInterval(checkAnalysisStatus, 2000);
        const metadataStatusInterval = setInterval(checkMetadataStatus, 2000);
        
        // Initial checks
        console.log('Running initial status checks');
        checkAnalysisStatus();
        checkMetadataStatus();
    }
    
    function updateLibraryStats() {
        const statsContainer = document.querySelector('.music-library-stats');
        if (!statsContainer) return;
        
        // Fetch library stats
        fetch('/api/library/stats')
            .then(response => response.json())
            .then(stats => {
                // Update stats in UI
                if (stats.status === 'success') {
                    const statData = stats.stats;
                    statsContainer.innerHTML = `
                        <div class="stat-item"><span>Tracks:</span> ${statData.total_tracks}</div>
                        <div class="stat-item"><span>With Metadata:</span> ${statData.tracks_with_metadata}</div>
                        <div class="stat-item"><span>Analyzed:</span> ${statData.analyzed_tracks}</div>
                    `;
                }
            })
            .catch(error => {
                console.error('Error fetching library stats:', error);
            });
    }
    
    function initializeSidebarNavigation() {
        // Add active class to current page link
        const currentPath = window.location.pathname;
        
        document.querySelectorAll('.sidebar-nav a, .nav-button').forEach(link => {
            const href = link.getAttribute('href');
            if (href === currentPath || 
                (currentPath === '/' && href === '#') ||
                (href !== '#' && currentPath.startsWith(href))) {
                link.classList.add('active');
            }
        });
    }
    
    // Retry loading playlists after a delay in case the server is still initializing
    function retryLoadPlaylists() {
        setTimeout(() => {
            window.loadSidebarPlaylists();
        }, 10000); // Try again after 10 seconds
    }
    
    // Set up a retry mechanism
    retryLoadPlaylists();
    
    // Make loadSidebarPlaylists globally accessible for other pages to call
    window.loadSidebarPlaylists = loadSidebarPlaylists;
});

// Function to load playlists into the sidebar
window.loadSidebarPlaylists = function() {
    // Use the correct ID that matches the sidebar.html file
    const playlistsContainer = document.getElementById('playlist-list');
    
    if (!playlistsContainer) {
        console.error('Playlists container not found in sidebar');
        return;
    }
    
    console.log('Loading playlists for sidebar');
    
    // Show loading indicator
    playlistsContainer.innerHTML = '<li class="loading">Loading playlists...</li>';
    
    // Use the correct API endpoint for playlists - UPDATED
    fetch('/api/playlists')
        .then(response => {
            console.log('Playlists response:', response);
            if (!response.ok) {
                throw new Error(`Playlist endpoint not available: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log('Playlists data:', data);
            
            // Clear loading indicator
            playlistsContainer.innerHTML = '';
            
            // Check if we got valid data
            if (!Array.isArray(data) || data.length === 0) {
                playlistsContainer.innerHTML = '<li class="empty-playlists">No playlists found</li>';
                return;
            }
            
            // Add each playlist to the sidebar
            data.forEach(playlist => {
                console.log('Processing playlist:', playlist); // Debug individual playlist object
                
                const playlistItem = document.createElement('li');
                playlistItem.className = 'playlist-item';
                
                const playlistLink = document.createElement('a');
                playlistLink.href = `/?playlist=${playlist.id}`;
                playlistLink.className = 'playlist-link';
                
                // Handle different playlist data structures
                // Check for name property in different possible locations
                let playlistName = 'Untitled Playlist';
                if (playlist.name) {
                    playlistName = playlist.name;
                } else if (playlist.playlist_name) {
                    playlistName = playlist.playlist_name;
                } else if (typeof playlist === 'object' && playlist !== null) {
                    // If playlist is an array with name at index 1 (common format in some APIs)
                    if (Array.isArray(playlist) && playlist.length > 1 && typeof playlist[1] === 'string') {
                        playlistName = playlist[1];
                    }
                    // Log keys to help debug the structure
                    console.log('Playlist keys:', Object.keys(playlist));
                }
                
                playlistLink.textContent = playlistName;
                playlistLink.title = playlist.description || '';
                
                // Add click handler
                playlistLink.addEventListener('click', function(e) {
                    e.preventDefault();
                    
                    // Update URL without reloading
                    const newUrl = `/?playlist=${playlist.id}`;
                    window.history.pushState({ url: newUrl }, '', newUrl);
                    
                    // Load the playlist content
                    if (typeof window.loadPlaylist === 'function') {
                        window.loadPlaylist(playlist.id);
                    } else {
                        console.error('loadPlaylist function not available');
                    }
                    
                    // Remove active class from all sidebar links
                    document.querySelectorAll('.sidebar a').forEach(link => {
                        link.classList.remove('active');
                    });
                });
                
                playlistItem.appendChild(playlistLink);
                playlistsContainer.appendChild(playlistItem);
            });
        })
        .catch(error => {
            console.error('Error loading playlists:', error);
            playlistsContainer.innerHTML = '<li class="error-playlists">Failed to load playlists</li>';
        });
};

// Load playlists when the document is loaded
document.addEventListener('DOMContentLoaded', function() {
    window.loadSidebarPlaylists();
});