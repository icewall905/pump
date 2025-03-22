document.addEventListener('DOMContentLoaded', function() {
    console.log('Navigation.js loaded with enhanced debugging');
    
    // Track audio player state
    const audioPlayer = document.getElementById('audio-player');
    
    // Define a global current track ID if it doesn't exist
    window.currentTrackId = window.currentTrackId || null;
    
    // Create a simple system for preserving audio state during navigation
    window.audioState = {
        save: function() {
            if (!audioPlayer) return null;
            
            // Get the Now Playing bar element
            const nowPlayingBar = document.getElementById('now-playing-bar');
            
            return {
                src: audioPlayer.src,
                currentTime: audioPlayer.currentTime,
                isPlaying: !audioPlayer.paused,
                volume: audioPlayer.volume,
                trackId: window.currentTrackId,
                nowPlayingActive: nowPlayingBar ? nowPlayingBar.classList.contains('active') : false,
                nowPlayingEmpty: nowPlayingBar ? nowPlayingBar.classList.contains('empty') : true,
                trackTitle: document.getElementById('now-playing-title')?.textContent,
                trackArtist: document.getElementById('now-playing-artist')?.textContent,
                trackArt: document.getElementById('now-playing-art')?.src
            };
        },
        restore: function(state) {
            if (!audioPlayer || !state) return;
            
            // Get the Now Playing bar element
            const nowPlayingBar = document.getElementById('now-playing-bar');
            const nowPlayingTitle = document.getElementById('now-playing-title');
            const nowPlayingArtist = document.getElementById('now-playing-artist');
            const nowPlayingArt = document.getElementById('now-playing-art');
            
            // Preserve current playback state
            const wasPlaying = !audioPlayer.paused;
            const currentSrc = audioPlayer.src;
            const currentTime = audioPlayer.currentTime;
            
            // Restore Now Playing bar state ONLY IF classes need to change
            if (nowPlayingBar) {
                if (state.nowPlayingActive && !nowPlayingBar.classList.contains('active')) {
                    nowPlayingBar.classList.add('active');
                } else if (!state.nowPlayingActive && nowPlayingBar.classList.contains('active')) {
                    nowPlayingBar.classList.remove('active');
                }
                
                if (state.nowPlayingEmpty && !nowPlayingBar.classList.contains('empty')) {
                    nowPlayingBar.classList.add('empty');
                } else if (!state.nowPlayingEmpty && nowPlayingBar.classList.contains('empty')) {
                    nowPlayingBar.classList.remove('empty');
                }
            }
            
            // Only update display info if it's different
            if (nowPlayingTitle && state.trackTitle && nowPlayingTitle.textContent !== state.trackTitle) {
                nowPlayingTitle.textContent = state.trackTitle;
            }
            
            if (nowPlayingArtist && state.trackArtist && nowPlayingArtist.textContent !== state.trackArtist) {
                nowPlayingArtist.textContent = state.trackArtist;
            }
            
            if (nowPlayingArt && state.trackArt && nowPlayingArt.src !== state.trackArt) {
                nowPlayingArt.src = state.trackArt;
            }
            
            // Only restore audio if we have a source and it's different from current
            if (state.src && state.src !== '' && state.src !== currentSrc) {
                console.log('Restoring audio source and state');
                audioPlayer.src = state.src;
                audioPlayer.currentTime = state.currentTime;
                audioPlayer.volume = state.volume;
                
                if (state.isPlaying) {
                    audioPlayer.play().catch(err => console.log('Auto-play prevented:', err));
                }
            } else if (state.src && state.src !== '' && state.src === currentSrc) {
                // If same source but time position changed significantly
                if (Math.abs(state.currentTime - currentTime) > 1) {
                    audioPlayer.currentTime = state.currentTime;
                }
                
                // Preserve playing state
                if (state.isPlaying && !wasPlaying) {
                    audioPlayer.play().catch(err => console.log('Auto-play prevented:', err));
                } else if (!state.isPlaying && wasPlaying) {
                    audioPlayer.pause();
                }
            }
            
            // Restore track ID
            if (state.trackId) {
                window.currentTrackId = state.trackId;
            }
        }
    };
    
    // Log the presence of critical DOM elements to help debug
    console.log('Critical DOM elements:');
    console.log('- audioPlayer:', !!audioPlayer);
    console.log('- nowPlayingBar:', !!document.getElementById('now-playing-bar'));
    console.log('- mainContent:', !!document.querySelector('.main-content'));
    console.log('- exploreLink:', !!document.getElementById('explore-link'));
    console.log('- recentLink:', !!document.getElementById('recent-link'));
    console.log('- likedLink:', !!document.getElementById('liked-link'));
    
    // Get the navigation links
    const exploreLink = document.getElementById('explore-link');
    const recentLink = document.getElementById('recent-link');
    const likedLink = document.getElementById('liked-link');
    
    // Define the navigation function with improved content replacement and audio state preservation
    function navigateTo(url) {
        console.log('Navigating to:', url);
        
        // Save audio state before navigation
        const savedAudioState = window.audioState.save();
        
        // Show loading indicator
        const mainContent = document.querySelector('.main-content');
        if (mainContent) {
            mainContent.classList.add('loading-content');
        }
        
        // Fetch the new page content
        fetch(url)
            .then(response => response.text())
            .then(html => {
                console.log('Received content from server for:', url);
                
                // Parse the HTML response
                const parser = new DOMParser();
                const doc = parser.parseFromString(html, 'text/html');
                
                // Extract only the main content from the fetched page
                const newContent = doc.querySelector('.main-content');
                
                if (newContent && mainContent) {
                    // Update page title
                    document.title = doc.title;
                    
                    // KEY FIX: Only replace the children of main-content instead of using innerHTML
                    // This preserves event handlers and prevents reflow of the whole document
                    const fragment = document.createDocumentFragment();
                    
                    // Clone all child nodes from the new content
                    Array.from(newContent.children).forEach(node => {
                        fragment.appendChild(node.cloneNode(true));
                    });
                    
                    // Clear existing content carefully
                    while (mainContent.firstChild) {
                        mainContent.removeChild(mainContent.firstChild);
                    }
                    
                    // Append new content
                    mainContent.appendChild(fragment);
                    mainContent.classList.remove('loading-content');
                    
                    // Update URL in the browser history
                    window.history.pushState({ url: url }, doc.title, url);
                    
                    // Restore audio state AFTER content replacement
                    window.audioState.restore(savedAudioState);
                    
                    // Update active navigation links
                    updateActiveNavigation(url);
                    
                    // Initialize any scripts needed for the new content
                    initializePageScripts(url);
                    
                    // Reinitialize player controls after navigation
                    reinitializePlayerControls();
                    
                    console.log('Content update complete for:', url);
                } else {
                    console.error('Could not extract main content from response for:', url);
                    console.error('newContent exists:', !!newContent);
                    console.error('mainContent exists:', !!mainContent);
                    
                    // Fallback to traditional navigation if content extraction fails
                    window.location.href = url;
                }
            })
            .catch(error => {
                console.error('Error during AJAX navigation:', error);
                // Fallback to traditional navigation on error
                window.location.href = url;
            });
    }
    
    // Special handler function for home subsection views
    function loadHomeSubsection(view) {
        console.log(`Loading home subsection: ${view}`);
        
        // Check if we're already on the home page
        const isHomePage = !window.location.pathname.includes('/library') && 
                           !window.location.pathname.includes('/settings') && 
                           !window.location.pathname.includes('/logs');
        
        // If not on home page, do a full navigation to the home page with view parameter
        if (!isHomePage) {
            console.log('Not on home page, navigating to home with view parameter');
            navigateTo(`/?view=${view}`);
            return;
        }
        
        // If already on home page, just update the view without full page reload
        console.log('Already on home page, updating view without reload');
        
        // Update active navigation
        updateActiveNavigation(`/?view=${view}`);
        
        // Update browser URL without reloading
        window.history.pushState({ url: `/?view=${view}` }, document.title, `/?view=${view}`);
        
        // Call the appropriate view loader function directly
        if (view === 'explore' && typeof window.loadExplore === 'function') {
            window.loadExplore();
        } else if (view === 'recent' && typeof window.loadRecent === 'function') {
            window.loadRecent();
        } else if (view === 'liked' && typeof window.loadLiked === 'function') {
            window.loadLiked();
        } else {
            console.error(`Function to load ${view} view not found, falling back to full navigation`);
            navigateTo(`/?view=${view}`);
        }
    }
    
    // Set up click handlers for special navigation links
    if (exploreLink) {
        exploreLink.addEventListener('click', function(e) {
            e.preventDefault();
            console.log('Explore link clicked');
            loadHomeSubsection('explore');
        });
    }
    
    if (recentLink) {
        recentLink.addEventListener('click', function(e) {
            e.preventDefault();
            console.log('Recent link clicked');
            loadHomeSubsection('recent');
        });
    }
    
    if (likedLink) {
        likedLink.addEventListener('click', function(e) {
            e.preventDefault();
            console.log('Liked link clicked');
            loadHomeSubsection('liked');
        });
    }
    
    // Enhance all navigation links to use AJAX instead of full page loads
    document.addEventListener('click', function(e) {
        // Find closest link ancestor
        const link = e.target.closest('a');
        if (!link) return;
        
        // Skip special links that are handled above
        if (link.id === 'explore-link' || link.id === 'recent-link' || link.id === 'liked-link') {
            return;
        }
        
        // Skip external links and links with specific attributes
        if (link.hostname !== window.location.hostname || 
            link.getAttribute('target') === '_blank' ||
            link.getAttribute('data-no-ajax') === 'true' ||
            link.href.includes('#')) {
            return;
        }
        
        // Prevent default navigation
        e.preventDefault();
        
        // Navigate to the URL
        navigateTo(link.href);
    });
    
    // Update the popstate handler to use loadHomeSubsection for home views
    window.addEventListener('popstate', function(e) {
        if (e.state && e.state.url) {
            console.log('Popstate navigation to:', e.state.url);
            
            // Extract view parameter for home subsections
            const url = e.state.url;
            const viewMatch = url.match(/[?&]view=([^&]*)/);
            
            // Special handling for home subsections
            if (viewMatch && ['explore', 'recent', 'liked'].includes(viewMatch[1])) {
                loadHomeSubsection(viewMatch[1]);
                return;
            }
            
            // For non-home views, continue with regular navigation
            const savedAudioState = window.audioState.save();
            
            // Rest of your existing popstate handler code...
            // ...
        }
    });
    
    // Helper function to update active navigation links
    function updateActiveNavigation(url) {
        console.log('Updating active navigation for URL:', url);
        
        // Remove active class from all nav links
        document.querySelectorAll('.nav-button').forEach(link => {
            link.classList.remove('active');
        });
        
        // Add active class to the matching link
        if (url.includes('/library')) {
            document.querySelector('.nav-button[href="/library"]')?.classList.add('active');
        } else if (url.includes('/settings')) {
            document.querySelector('.nav-button[href="/settings"]')?.classList.add('active');
        } else if (url.includes('/logs')) {
            document.querySelector('.nav-button[href="/logs"]')?.classList.add('active');
        } else if (url.includes('view=liked')) {
            document.querySelector('#liked-link')?.classList.add('active');
        } else if (url.includes('view=explore')) {
            document.querySelector('#explore-link')?.classList.add('active');
        } else if (url.includes('view=recent')) {
            document.querySelector('#recent-link')?.classList.add('active');
        } else {
            document.querySelector('.nav-button[href="/"]')?.classList.add('active');
        }
    }
    
    // Helper function to initialize page-specific scripts
    function initializePageScripts(url) {
        console.log('Initializing scripts for URL:', url);
        
        // Initialize scripts based on the current page
        if (url.includes('/library')) {
            console.log('Loading library page scripts');
            if (window.initLibraryPage) {
                console.log('Calling window.initLibraryPage()');
                window.initLibraryPage();
            } else {
                console.log('Loading library.js script');
                loadScript('/static/js/library.js');
            }
        } else if (url.includes('/settings')) {
            console.log('Loading settings page scripts');
            if (window.initSettingsPage) {
                console.log('Calling window.initSettingsPage()');
                window.initSettingsPage();
            } else {
                console.log('Loading settings.js script');
                loadScript('/static/js/settings.js');
            }
        } else if (url.includes('/logs')) {
            console.log('Initializing logs page');
            initLogsPage();
        } else {
            // Home page (including liked, explore, recent)
            console.log('Loading home page scripts');
            
            // Process URL parameters for view
            const urlParams = new URLSearchParams(new URL(url).search);
            const view = urlParams.get('view');
            
            console.log('Home page view:', view);
            
            // Try to load player functions if needed
            if (window.initPlayerPage) {
                console.log('Calling window.initPlayerPage()');
                window.initPlayerPage();
            }
            
            // Handle specific views
            if (view === 'explore') {
                console.log('Loading explore view');
                setTimeout(() => {
                    if (typeof window.loadExplore === 'function') {
                        window.loadExplore();
                    } else {
                        console.error('loadExplore function not found');
                    }
                }, 100); // Small delay to ensure DOM is ready
            } else if (view === 'recent') {
                console.log('Loading recent view');
                setTimeout(() => {
                    if (typeof window.loadRecent === 'function') {
                        window.loadRecent();
                    } else {
                        console.error('loadRecent function not found');
                    }
                }, 100);
            } else if (view === 'liked') {
                console.log('Loading liked view');
                setTimeout(() => {
                    if (typeof window.loadLiked === 'function') {
                        window.loadLiked();
                    } else {
                        console.error('loadLiked function not found');
                    }
                }, 100);
            }
        }
        
        // Always reinitialize player controls after navigation
        reinitializePlayerControls();
    }
    
    // Helper function to load a script dynamically if it doesn't exist
    function loadScript(src) {
        if (document.querySelector(`script[src="${src}"]`)) {
            console.log(`Script already loaded: ${src}`);
            return;
        }
        
        console.log(`Dynamically loading script: ${src}`);
        const script = document.createElement('script');
        script.src = src;
        script.onload = function() {
            console.log(`Script loaded: ${src}`);
            
            // Call the initialization function after loading the script
            if (src.includes('library.js') && window.initLibraryPage) {
                window.initLibraryPage();
            } else if (src.includes('settings.js') && window.initSettingsPage) {
                window.initSettingsPage();
            } else if (src.includes('player.js') && window.initPlayerPage) {
                window.initPlayerPage();
            }
        };
        document.head.appendChild(script);
    }
    
    // Initialize logs page functionality
    function initLogsPage() {
        console.log('Initializing logs page');
        const logLines = document.getElementById('log-lines');
        const refreshBtn = document.getElementById('refresh-logs');
        const downloadBtn = document.getElementById('download-logs');
        const logContent = document.getElementById('log-content');
        
        if (logLines && refreshBtn && logContent) {
            console.log('Found log page elements, setting up functionality');
            loadLogs();
            
            // Set up event listeners
            refreshBtn.addEventListener('click', loadLogs);
            logLines.addEventListener('change', loadLogs);
            
            if (downloadBtn) {
                downloadBtn.addEventListener('click', function() {
                    window.location.href = '/api/logs/download';
                });
            }
        } else {
            console.error('Missing log page elements:');
            console.error('- logLines:', !!logLines);
            console.error('- refreshBtn:', !!refreshBtn);
            console.error('- logContent:', !!logContent);
        }
        
        function loadLogs() {
            const lines = logLines.value;
            logContent.innerHTML = '<div class="loading">Loading logs...</div>';
            
            console.log('Loading logs with', lines, 'lines');
            fetch(`/api/logs/view?lines=${lines}`)
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        logContent.innerHTML = `<div class="error">${data.error}</div>`;
                        return;
                    }
                    
                    if (!data.logs || data.logs.length === 0) {
                        logContent.innerHTML = '<div class="empty">No logs found</div>';
                        return;
                    }
                    
                    logContent.innerHTML = '';
                    data.logs.forEach(line => {
                        const logLine = document.createElement('div');
                        logLine.className = 'log-line';
                        logLine.textContent = line;
                        
                        // Add color based on log level
                        if (line.includes(' DEBUG ')) logLine.classList.add('log-debug');
                        if (line.includes(' INFO ')) logLine.classList.add('log-info');
                        if (line.includes(' WARNING ')) logLine.classList.add('log-warning');
                        if (line.includes(' ERROR ')) logLine.classList.add('log-error');
                        if (line.includes(' CRITICAL ')) logLine.classList.add('log-critical');
                        
                        logContent.appendChild(logLine);
                    });
                    
                    // Scroll to bottom
                    logContent.scrollTop = logContent.scrollHeight;
                })
                .catch(error => {
                    logContent.innerHTML = `<div class="error">Error loading logs: ${error}</div>`;
                });
        }
    }
    
    // Add this function after your navigateTo function or anywhere in your navigation.js file

    function reinitializePlayerControls() {
        console.log('Reinitializing player controls after navigation');
        
        // Get references to DOM elements
        const playPauseButton = document.getElementById('play-pause');
        const audioPlayer = document.getElementById('audio-player');
        
        // Check if elements exist
        if (!playPauseButton || !audioPlayer) {
            console.error('Missing required elements for player controls');
            console.log('playPauseButton exists:', !!playPauseButton);
            console.log('audioPlayer exists:', !!audioPlayer);
            return;
        }
        
        // Remove any existing event listeners by cloning and replacing
        const newButton = playPauseButton.cloneNode(true);
        playPauseButton.parentNode.replaceChild(newButton, playPauseButton);
        
        // Add fresh event listener
        newButton.addEventListener('click', function() {
            console.log('Play/Pause button clicked');
            
            if (!audioPlayer) return;
            
            if (audioPlayer.paused) {
                console.log('Audio was paused, attempting to play');
                audioPlayer.play()
                    .then(() => {
                        console.log('Audio started playing');
                        newButton.textContent = '⏸'; // Pause symbol
                        newButton.title = 'Pause';
                    })
                    .catch(error => {
                        console.error('Play prevented:', error);
                    });
            } else {
                console.log('Audio was playing, pausing');
                audioPlayer.pause();
                newButton.textContent = '▶'; // Play symbol
                newButton.title = 'Play';
            }
        });
        
        // Update the button to match current state
        if (audioPlayer && !audioPlayer.paused) {
            newButton.textContent = '⏸';
            newButton.title = 'Pause';
        } else {
            newButton.textContent = '▶';
            newButton.title = 'Play';
        }
        
        console.log('Play/Pause button reinitialized');
    }
});

window.addEventListener('load', function() {
    if (window.resumeStatusPolling) {
        setTimeout(window.resumeStatusPolling, 500);
    }
});