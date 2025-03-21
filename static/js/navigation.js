// Updated navigation module with fixes for content loading issues

document.addEventListener('DOMContentLoaded', function() {
    // Track audio player state
    const audioPlayer = document.getElementById('audio-player');
    
    // Create a simple system for preserving audio state during navigation
    window.audioState = {
        save: function() {
            if (!audioPlayer) return null;
            
            return {
                src: audioPlayer.src,
                currentTime: audioPlayer.currentTime,
                isPlaying: !audioPlayer.paused,
                volume: audioPlayer.volume
            };
        },
        restore: function(state) {
            if (!audioPlayer || !state || !state.src) return;
            
            // Only restore if we have actual audio
            if (state.src && state.src !== '') {
                audioPlayer.src = state.src;
                audioPlayer.currentTime = state.currentTime;
                audioPlayer.volume = state.volume;
                
                if (state.isPlaying) {
                    audioPlayer.play().catch(err => console.log('Auto-play prevented:', err));
                }
            }
        }
    };
    
    // Improve navigation links with minimal interference - just preserve audio
    document.addEventListener('click', function(e) {
        // Find closest link ancestor
        const link = e.target.closest('a');
        if (!link) return;
        
        // Skip external links and links with specific attributes
        if (link.hostname !== window.location.hostname || 
            link.getAttribute('target') === '_blank' ||
            link.getAttribute('data-no-ajax') === 'true' ||
            link.href.includes('#')) {
            return;
        }
        
        // Pause status polling during navigation
        if (window.pauseStatusPolling) {
            window.pauseStatusPolling();
        }
        
        // Save audio state before navigation
        const savedAudioState = window.audioState.save();
        
        // Store in sessionStorage to survive page navigation
        if (savedAudioState) {
            sessionStorage.setItem('audioState', JSON.stringify(savedAudioState));
            sessionStorage.setItem('audioStateTimestamp', Date.now());
        }
    });
    
    // Check for saved audio state on page load
    const savedState = sessionStorage.getItem('audioState');
    const timestamp = sessionStorage.getItem('audioStateTimestamp');
    
    if (savedState && timestamp) {
        // Only restore if saved less than 30 seconds ago
        const age = Date.now() - parseInt(timestamp);
        if (age < 30000) {
            try {
                const state = JSON.parse(savedState);
                setTimeout(() => {
                    window.audioState.restore(state);
                }, 500); // Small delay to ensure player is ready
            } catch (e) {
                console.error('Error restoring audio state:', e);
            }
        } else {
            // Clear old state
            sessionStorage.removeItem('audioState');
            sessionStorage.removeItem('audioStateTimestamp');
        }
    }
    
    // Initialize view based on URL
    function initViewFromUrl() {
        const urlParams = new URLSearchParams(window.location.search);
        const view = urlParams.get('view');
        
        // Initialize correct view based on URL parameter
        if (view === 'liked' && typeof loadLiked === 'function') {
            loadLiked();
            setActiveNav('liked');
        } else if (view === 'explore' && typeof loadExplore === 'function') {
            loadExplore();
            setActiveNav('explore');
        } else if (view === 'recent' && typeof loadRecent === 'function') {
            loadRecent();
            setActiveNav('recent');
        } else if (!view && typeof loadExplore === 'function') {
            // Default view
            loadExplore();
            setActiveNav('home');
        }
    }
    
    // Initialize view now
    initViewFromUrl();
    
    // Add event listeners for view navigation with traditional page loads
    document.getElementById('liked-link')?.addEventListener('click', function(e) {
        e.preventDefault();
        // Save audio state
        const state = window.audioState.save();
        if (state) {
            sessionStorage.setItem('audioState', JSON.stringify(state));
            sessionStorage.setItem('audioStateTimestamp', Date.now());
        }
        window.location.href = '/?view=liked';
    });
    
    document.getElementById('explore-link')?.addEventListener('click', function(e) {
        e.preventDefault();
        // Save audio state
        const state = window.audioState.save();
        if (state) {
            sessionStorage.setItem('audioState', JSON.stringify(state));
            sessionStorage.setItem('audioStateTimestamp', Date.now());
        }
        window.location.href = '/?view=explore';
    });
    
    document.getElementById('recent-link')?.addEventListener('click', function(e) {
        e.preventDefault();
        // Save audio state
        const state = window.audioState.save();
        if (state) {
            sessionStorage.setItem('audioState', JSON.stringify(state));
            sessionStorage.setItem('audioStateTimestamp', Date.now());
        }
        window.location.href = '/?view=recent';
    });
    
    document.getElementById('home-link')?.addEventListener('click', function(e) {
        e.preventDefault();
        // Save audio state
        const state = window.audioState.save();
        if (state) {
            sessionStorage.setItem('audioState', JSON.stringify(state));
            sessionStorage.setItem('audioStateTimestamp', Date.now());
        }
        window.location.href = '/';
    });
    
    // Handle back/forward navigation
    window.addEventListener('popstate', function(e) {
        if (e.state && e.state.url) {
            // Load content for the back/forward navigation
            fetch(e.state.url)
                .then(response => response.text())
                .then(html => {
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(html, 'text/html');
                    
                    const newContent = doc.querySelector('.main-content');
                    const currentContent = document.querySelector('.main-content');
                    
                    if (newContent && currentContent) {
                        document.title = doc.title;
                        currentContent.innerHTML = newContent.innerHTML;
                        initializePageScripts();
                        updateActiveNavigation(e.state.url);
                    } else {
                        window.location.href = e.state.url;
                    }
                })
                .catch(error => {
                    console.error('Error during popstate navigation:', error);
                    window.location.href = e.state.url;
                });
        }
    });
    
    // Helper function to re-initialize scripts after content change
    function initializePageScripts() {
        // Run any necessary initialization for the new page content
        // For example, reattach event listeners or initialize components
        
        if (typeof loadExplore === 'function' && window.location.href.includes('view=explore')) {
            loadExplore();
        } else if (typeof loadRecent === 'function' && window.location.href.includes('view=recent')) {
            loadRecent();
        } else if (typeof loadLiked === 'function' && window.location.href.includes('view=liked')) {
            loadLiked();
        }
        
        // Re-initialize any common components
        const playlistContainer = document.getElementById('playlist-container');
        if (playlistContainer) {
            if (window.location.href.includes('view=liked')) {
                playlistContainer.style.display = 'none';
            } else {
                playlistContainer.style.display = 'block';
            }
        }
    }
    
    // Helper function to update active navigation
    function updateActiveNavigation(url) {
        // Remove active class from all nav links
        document.querySelectorAll('.sidebar-nav a').forEach(link => {
            link.classList.remove('active');
        });
        
        // Determine which nav link should be active based on URL
        if (url.includes('view=explore')) {
            document.getElementById('explore-link')?.classList.add('active');
        } else if (url.includes('view=recent')) {
            document.getElementById('recent-link')?.classList.add('active');
        } else if (url.includes('view=liked')) {
            document.getElementById('liked-link')?.classList.add('active');
        } else if (url === '/' || url === '') {
            document.getElementById('home-link')?.classList.add('active');
        }
    }
    
    // Global analysis status checking
    if (window.checkGlobalAnalysisStatus) {
        // Start checking for global status updates
        window.checkGlobalAnalysisStatus();
    }

    // Resume status polling when the page has loaded
    if (window.resumeStatusPolling) {
        window.resumeStatusPolling();
    }
});

// Also handle the window load event
window.addEventListener('load', function() {
    if (window.resumeStatusPolling) {
        setTimeout(window.resumeStatusPolling, 500);
    }
});