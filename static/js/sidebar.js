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
            // Only retry loading if playlists haven't been loaded successfully yet
            console.log('Retrying playlist load...');
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
    console.log('Loading playlists from API');
    
    const playlistsContainer = document.getElementById('playlist-list');
    if (!playlistsContainer) {
        console.error('Playlists container not found in sidebar.');
        return;
    }

    playlistsContainer.innerHTML = '<li class="loading">Loading playlists...</li>';
    
    fetch('/api/playlists')
        .then(response => {
            console.log('Playlists response status:', response.status, 'ok:', response.ok);
            if (!response.ok) {
                // Try to get error message from response body
                return response.json().then(errData => {
                    throw new Error(`Playlist endpoint not available: ${response.status} - ${errData.error || 'Unknown server error'}`);
                }).catch(() => {
                    // If parsing error body fails
                    throw new Error(`Playlist endpoint not available: ${response.status}`);
                });
            }
            return response.json();
        })
        .then(data => {
            console.log('Playlists data received (raw from server):', JSON.stringify(data, null, 2));
            console.log('Type of received data:', typeof data, 'Is Array:', Array.isArray(data));
            
            playlistsContainer.innerHTML = ''; 
            
            if (!Array.isArray(data)) {
                console.error('Playlists data is not an array:', data);
                playlistsContainer.innerHTML = '<li class="error-playlists">Error: Invalid playlist data format from server</li>';
                return;
            }

            if (data.length === 0) {
                playlistsContainer.innerHTML = '<li class="empty-playlists">No playlists found</li>';
                return;
            }
            
            let playlistsAdded = 0;
            data.forEach(playlist => {
                console.log('Processing playlist:', playlist, 'Type:', typeof playlist);

                if (typeof playlist !== 'object' || playlist === null) {
                    console.error('Playlist item is not an object:', playlist);
                    return; // Skip this non-object item
                }

                const playlistId = playlist.id || playlist.playlist_id || playlist._id; 

                if (playlistId === undefined || playlistId === null) { // Added null check
                    console.error('Playlist ID is undefined or null for playlist:', playlist);
                    // Do not return; allow other playlists to be processed.
                    // This item will be skipped for rendering.
                } else {
                    const playlistItem = document.createElement('li');
                    playlistItem.className = 'playlist-item';

                    const playlistLink = document.createElement('a');
                    playlistLink.href = `/?playlist=${playlistId}`; 
                    playlistLink.className = 'playlist-link';

                    let playlistName = 'Untitled Playlist';
                    if (playlist.name) {
                        playlistName = playlist.name;
                    } else if (playlist.playlist_name) {
                        playlistName = playlist.playlist_name;
                    } else if (typeof playlist === 'object' && playlist !== null) {
                        if (Array.isArray(playlist) && playlist.length > 1 && typeof playlist[1] === 'string') {
                            playlistName = playlist[1];
                        }
                    }
                    
                    playlistLink.textContent = playlistName;
                    playlistLink.title = playlist.description || '';
                    
                    playlistLink.addEventListener('click', function(e) {
                        e.preventDefault();
                        
                        // Re-check ID just in case, though it should be valid here
                        const currentId = playlist.id || playlist.playlist_id || playlist._id;
                        if (currentId === undefined || currentId === null) {
                            console.error("Cannot load playlist: ID is undefined or null at click time.");
                            return;
                        }
                        const newUrl = `/?playlist=${currentId}`;
                        window.history.pushState({ url: newUrl }, '', newUrl);
                        
                        if (typeof window.loadPlaylist === 'function') {
                            window.loadPlaylist(currentId); 
                        } else {
                            console.error('loadPlaylist function not available');
                        }
                        
                        document.querySelectorAll('.sidebar a').forEach(link => {
                            link.classList.remove('active');
                        });
                        // this.classList.add('active'); // Active class should be set by navigation logic or after load
                    });
                    
                    playlistItem.appendChild(playlistLink);
                    playlistsContainer.appendChild(playlistItem);
                    playlistsAdded++;
                }
            });
            
            if (playlistsAdded === 0 && data.length > 0) {
                playlistsContainer.innerHTML = '<li class="empty-playlists">No valid playlists to display (all items lacked a valid ID).</li>';
            } else if (playlistsAdded === 0 && data.length === 0) {
                // This case is already handled by "No playlists found"
            } else if (playlistsAdded > 0) {
                console.log(`Playlists loaded successfully, count: ${playlistsAdded}`);
            }
        })
        .catch(error => {
            console.error('Error loading playlists:', error.message);
            if (playlistsContainer) {
                playlistsContainer.innerHTML = `<li class="error-playlists">Failed to load playlists: ${error.message}</li>`;
            }
        });
};

document.addEventListener('DOMContentLoaded', function() {
    // Only call loadSidebarPlaylists if it hasn't been loaded already
    if (typeof window.loadSidebarPlaylists === 'function') {
        window.loadSidebarPlaylists();
    } else if (!window.loadSidebarPlaylists) {
        console.error("loadSidebarPlaylists is not defined globally when DOMContentLoaded fires.");
    }

    const navLinks = document.querySelectorAll('.sidebar .nav-buttons > a, .sidebar .sub-nav-buttons > a');
    navLinks.forEach(link => {
        link.addEventListener('click', function() {
            document.querySelectorAll('.sidebar a').forEach(lnk => {
                lnk.classList.remove('active');
            });
            this.classList.add('active');
        });
    });
});