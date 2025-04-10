// Sidebar functionality
document.addEventListener('DOMContentLoaded', function() {
    console.log('Initializing sidebar.js');
    
    // Global status indicator elements
    const analysisStatusIndicator = document.getElementById('analysis-sidebar-progress');
    const metadataStatusIndicator = document.getElementById('metadata-sidebar-progress');
    
    // Initialize library stats
    updateLibraryStats();
    
    // Check for status indicators
    if (analysisStatusIndicator && metadataStatusIndicator) {
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
                    // Update UI with status
                    if (data.running) {
                        analysisStatusIndicator.classList.add('active');
                        analysisStatusIndicator.innerHTML = `
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${data.percent_complete}%"></div>
                            </div>
                            <div class="progress-status-text">
                                Analyzing: ${data.percent_complete}% complete
                            </div>
                        `;
                    } else {
                        analysisStatusIndicator.classList.remove('active');
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
                    if (data.running) {
                        metadataStatusIndicator.classList.add('active');
                        metadataStatusIndicator.innerHTML = `
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${data.percent_complete}%"></div>
                            </div>
                            <div class="progress-status-text">
                                Updating metadata: ${data.percent_complete}% complete
                            </div>
                        `;
                    } else {
                        metadataStatusIndicator.classList.remove('active');
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