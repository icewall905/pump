/**
 * Save Playlist Fix - Direct approach to fix the save playlist functionality
 */

// Execute immediately when script loads
(function() {
    console.log('Save Playlist Fix: Script loaded');
    
    // Function to initialize the save playlist functionality
    function initSavePlaylist() {
        console.log('Save Playlist Fix: Initializing...');
        
        // Get the save button by ID
        const savePlaylistBtn = document.getElementById('save-playlist-btn');
        console.log('Save Playlist Button found:', !!savePlaylistBtn);
        
        if (!savePlaylistBtn) {
            console.error('Save Playlist Fix: Button not found!');
            return false;
        }
        
        // Get the modal and form elements
        const savePlaylistModal = document.getElementById('save-playlist-modal');
        const savePlaylistForm = document.getElementById('save-playlist-form');
        const closeModalBtn = savePlaylistModal ? savePlaylistModal.querySelector('.close') : null;
        
        console.log('Save Playlist Fix: Modal found:', !!savePlaylistModal);
        console.log('Save Playlist Fix: Form found:', !!savePlaylistForm);
        
        // Attach event listener to the save button
        savePlaylistBtn.addEventListener('click', function(e) {
            e.preventDefault();
            console.log('Save Playlist Fix: Button clicked');
            openSavePlaylistModal();
        });
        
        // Close modal button
        if (closeModalBtn) {
            closeModalBtn.addEventListener('click', function() {
                closeSavePlaylistModal();
            });
        }
        
        // Form submission
        if (savePlaylistForm) {
            savePlaylistForm.addEventListener('submit', function(e) {
                e.preventDefault();
                handleSavePlaylistSubmit();
            });
        }
        
        // Close when clicking outside
        window.addEventListener('click', function(e) {
            if (savePlaylistModal && e.target === savePlaylistModal) {
                closeSavePlaylistModal();
            }
        });
        
        // Make the global function available
        window.saveCurrentPlaylist = openSavePlaylistModal;
        
        return true;
    }
    
    // Function to open the save playlist modal
    function openSavePlaylistModal() {
        console.log('Save Playlist Fix: Opening modal');
        
        const savePlaylistModal = document.getElementById('save-playlist-modal');
        const playlistNameInput = document.getElementById('playlist-name');
        
        // Check if we have a playlist to save
        if (!window.currentPlaylist || window.currentPlaylist.length === 0) {
            console.error('Save Playlist Fix: No playlist to save');
            showToast('No playlist to save', 'error');
            return;
        }
        
        // Show the modal
        if (savePlaylistModal) {
            savePlaylistModal.style.display = 'block';
            
            // Focus on the name input
            if (playlistNameInput) {
                setTimeout(() => {
                    playlistNameInput.focus();
                }, 100);
            }
        } else {
            console.error('Save Playlist Fix: Modal not found');
            showToast('Save playlist feature is not available', 'error');
        }
    }
    
    // Function to close the save playlist modal
    function closeSavePlaylistModal() {
        const savePlaylistModal = document.getElementById('save-playlist-modal');
        const playlistNameInput = document.getElementById('playlist-name');
        const playlistDescriptionInput = document.getElementById('playlist-description');
        
        if (savePlaylistModal) {
            savePlaylistModal.style.display = 'none';
            
            // Clear form fields
            if (playlistNameInput) playlistNameInput.value = '';
            if (playlistDescriptionInput) playlistDescriptionInput.value = '';
        }
    }
    
    // Function to handle form submission
    function handleSavePlaylistSubmit() {
        console.log('Save Playlist Fix: Handling form submission');
        
        const playlistNameInput = document.getElementById('playlist-name');
        const playlistDescriptionInput = document.getElementById('playlist-description');
        
        if (!playlistNameInput) {
            console.error('Save Playlist Fix: Playlist name input not found');
            return;
        }
        
        // Check if the currentPlaylist global variable exists and has tracks
        if (!window.currentPlaylist || window.currentPlaylist.length === 0) {
            console.error('Save Playlist Fix: No playlist to save');
            showToast('No playlist to save', 'error');
            return;
        }
        
        const name = playlistNameInput.value.trim();
        const description = playlistDescriptionInput ? playlistDescriptionInput.value.trim() : '';
        
        if (!name) {
            showToast('Please enter a playlist name', 'error');
            playlistNameInput.focus();
            return;
        }
        
        // Get track IDs
        const tracks = window.currentPlaylist.map(track => track.id);
        
        // Prepare the data
        const playlistData = {
            name: name,
            description: description,
            tracks: tracks
        };
        
        console.log('Saving playlist with data:', playlistData);
        
        // Save playlist with proper error handling
        fetch('/api/playlists', { // Corrected endpoint
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(playlistData)
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(`Server returned ${response.status}: ${data.error || 'Unknown error'}`);
                });
            }
            return response.json();
        })
        .then(data => {
            console.log('Save Playlist Fix: Playlist saved successfully:', data);
            
            // Show success message
            showToast('Playlist saved successfully!');
            
            // Close the modal
            closeSavePlaylistModal();
            
            // Reload playlists in sidebar
            if (typeof window.loadSidebarPlaylists === 'function') {
                window.loadSidebarPlaylists();
            }
        })
        .catch(error => {
            console.error('Save Playlist Fix: Error saving playlist:', error);
            
            // Show error message
            showToast(`Error saving playlist: ${error.message}`, 'error');
        });
    }
    
    // Function to show toast notifications
    function showToast(message, type = 'success') {
        // Check if toast container exists, create if not
        let toastContainer = document.querySelector('.toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.className = 'toast-container';
            document.body.appendChild(toastContainer);
        }
        
        // Create toast
        const toast = document.createElement('div');
        toast.className = `toast-notification ${type}`;
        toast.textContent = message;
        toastContainer.appendChild(toast);
        
        // Remove after 3 seconds
        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => {
                toast.remove();
            }, 500);
        }, 3000);
    }
    
    // Initialize when DOM is ready
    function init() {
        console.log('Save Playlist Fix: DOM loaded, initializing');
        
        if (!initSavePlaylist()) {
            // If initialization fails, retry after a short delay
            console.log('Save Playlist Fix: Initialization failed, will retry in 500ms');
            setTimeout(initSavePlaylist, 500);
        }
    }
    
    // Initialize immediately if DOM is already loaded
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        init();
    } else {
        // Otherwise wait for DOM to be ready
        document.addEventListener('DOMContentLoaded', init);
    }
    
    // Also try to initialize when window is fully loaded
    window.addEventListener('load', function() {
        console.log('Save Playlist Fix: Window load event fired');
        initSavePlaylist();
    });
})();