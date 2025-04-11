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
    loadSidebarPlaylists();
    
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
    
    // Function to load playlists in the sidebar
    function loadSidebarPlaylists() {
        const playlistList = document.getElementById('playlist-list');
        if (!playlistList) {
            console.error('Playlist list container not found');
            return;
        }
        
        console.log('Loading playlists for sidebar');
        
        // Set a timeout to handle failed/slow loading
        const loadingTimeout = setTimeout(() => {
            // If we haven't replaced the content after 8 seconds, show error
            if (playlistList.innerHTML.includes('Loading playlists...')) {
                playlistList.innerHTML = '<div class="empty">No playlists available</div>';
            }
        }, 8000);
        
        // Fetch playlists from API
        fetch('/api/playlists')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                clearTimeout(loadingTimeout);
                
                console.log('Playlists loaded:', data);
                
                if (!Array.isArray(data) || data.length === 0) {
                    playlistList.innerHTML = '<div class="empty">No playlists yet</div>';
                    return;
                }
                
                let html = '';
                data.forEach(playlist => {
                    html += `
                        <div class="playlist-item" data-id="${playlist.id}">
                            <div class="playlist-name">${playlist.name}</div>
                            <div class="playlist-count">${playlist.track_count}</div>
                        </div>
                    `;
                });
                
                playlistList.innerHTML = html;
                
                // Add click handlers for playlist items
                document.querySelectorAll('.playlist-item').forEach(item => {
                    item.addEventListener('click', function() {
                        const playlistId = this.getAttribute('data-id');
                        if (typeof window.loadPlaylist === 'function') {
                            window.loadPlaylist(playlistId);
                        } else {
                            // Fallback to regular navigation
                            window.location.href = `/playlist/${playlistId}`;
                        }
                    });
                });
            })
            .catch(error => {
                clearTimeout(loadingTimeout);
                console.error('Error loading playlists:', error);
                playlistList.innerHTML = '<div class="error">Failed to load playlists</div>';
            });
    }
    
    function initializeStatusChecking() {
        // Check analysis status periodically
        function checkAnalysisStatus() {
            fetch('/api/analysis/status')
                .then(response => response.json())
                .then(data => {
                    console.log('Analysis status update:', data);
                    // Update UI with status
                    if (data.running) {
                        // Make the indicator visible - force display with !important
                        analysisStatusIndicator.style.cssText = 'display: block !important; visibility: visible !important; opacity: 1 !important; background-color: rgba(0,0,0,0.3); padding: 10px; margin: 10px 0; border-radius: 4px;';
                        analysisStatusIndicator.classList.add('active');
                        analysisStatusIndicator.innerHTML = `
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${data.percent_complete}%; background-color: #4caf50;"></div>
                            </div>
                            <div class="progress-status-text" style="color: white; font-size: 12px; text-align: center; margin-top: 5px;">
                                Analyzing: ${data.percent_complete}% complete
                            </div>
                        `;
                        console.log('Analysis progress shown:', data.percent_complete + '%');
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
});