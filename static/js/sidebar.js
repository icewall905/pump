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
    
    function initializeStatusChecking() {
        // Check analysis status periodically
        function checkAnalysisStatus() {
            fetch('/api/analysis/status')
                .then(response => response.json())
                .then(data => {
                    if (data.running) {
                        // Show the progress indicator
                        analysisStatusIndicator.style.display = 'block';
                        
                        // Update progress bar
                        const progressFill = analysisStatusIndicator.querySelector('.progress-fill');
                        if (progressFill) {
                            progressFill.style.width = data.percent_complete + '%';
                        }
                        
                        // Update progress text
                        const statusText = analysisStatusIndicator.querySelector('.progress-status-text');
                        if (statusText) {
                            statusText.textContent = `Analysis in progress: ${data.percent_complete}% complete`;
                        }
                    } else {
                        // Hide the progress indicator when not running
                        analysisStatusIndicator.style.display = 'none';
                    }
                })
                .catch(error => {
                    console.error('Error checking analysis status:', error);
                });
        }
        
        // Check metadata update status periodically
        function checkMetadataStatus() {
            fetch('/api/metadata-update/status')
                .then(response => response.json())
                .then(data => {
                    if (data.running) {
                        // Show the progress indicator
                        metadataStatusIndicator.style.display = 'block';
                        
                        // Update progress bar
                        const progressFill = metadataStatusIndicator.querySelector('.progress-fill');
                        if (progressFill) {
                            progressFill.style.width = data.percent_complete + '%';
                        }
                        
                        // Update progress text
                        const statusText = metadataStatusIndicator.querySelector('.progress-status-text');
                        if (statusText) {
                            statusText.textContent = `Metadata update: ${data.percent_complete}% complete`;
                        }
                    } else {
                        // Hide the progress indicator when not running
                        metadataStatusIndicator.style.display = 'none';
                    }
                })
                .catch(error => {
                    console.error('Error checking metadata status:', error);
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
                if (stats.error) {
                    console.error('Error fetching stats:', stats.error);
                    return;
                }
                
                // Update stats in sidebar
                const trackCountElement = statsContainer.querySelector('.track-count');
                const artistCountElement = statsContainer.querySelector('.artist-count');
                const albumCountElement = statsContainer.querySelector('.album-count');
                
                if (trackCountElement) trackCountElement.textContent = stats.track_count || '0';
                if (artistCountElement) artistCountElement.textContent = stats.artist_count || '0';
                if (albumCountElement) albumCountElement.textContent = stats.album_count || '0';
            })
            .catch(error => {
                console.error('Error fetching library stats:', error);
            });
    }
    
    function initializeSidebarNavigation() {
        // Add active class to current page link
        const currentPath = window.location.pathname;
        
        document.querySelectorAll('.sidebar-nav a, .nav-button').forEach(link => {
            if (link.getAttribute('href') === currentPath) {
                link.classList.add('active');
            }
            
            // For subpages like /home?view=recent
            if (currentPath.includes('/home') && window.location.search) {
                const view = new URLSearchParams(window.location.search).get('view');
                if (view && link.getAttribute('href').includes(`view=${view}`)) {
                    link.classList.add('active');
                }
            }
        });
    }
});