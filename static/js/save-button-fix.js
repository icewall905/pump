/**
 * Save Button Fix - Immediate fix for the Save Playlist button's disabled state
 * This script removes the disabled attribute and ensures event listeners are properly attached
 */

(function() {
    console.log('Save Button Fix: Script loaded');
    
    // Function to fix the save button
    function fixSaveButton() {
        console.log('Save Button Fix: Attempting to fix the button');
        
        // Get the save playlist button
        const savePlaylistBtn = document.getElementById('save-playlist-btn');
        
        if (!savePlaylistBtn) {
            console.error('Save Button Fix: Button not found!');
            return false;
        }
        
        console.log('Save Button Fix: Button found, current disabled state:', savePlaylistBtn.disabled);
        
        // Remove the disabled attribute
        savePlaylistBtn.removeAttribute('disabled');
        
        // Check if event listeners are attached by setting a flag
        if (!savePlaylistBtn._hasFixedClickHandler) {
            console.log('Save Button Fix: Adding click event listener');
            
            // Add a direct click handler
            savePlaylistBtn.addEventListener('click', function(e) {
                console.log('Save Button Fix: Button clicked');
                
                // If there's an existing handler, try to call it
                if (typeof window.saveCurrentPlaylist === 'function') {
                    console.log('Save Button Fix: Calling saveCurrentPlaylist function');
                    window.saveCurrentPlaylist();
                } else {
                    console.log('Save Button Fix: No saveCurrentPlaylist function found, showing modal directly');
                    // Fallback to showing the modal directly
                    const modal = document.getElementById('save-playlist-modal');
                    if (modal) {
                        modal.style.display = 'block';
                    } else {
                        console.error('Save Button Fix: Modal not found');
                        alert('Save playlist modal not found');
                    }
                }
            });
            
            // Mark that we've added our handler
            savePlaylistBtn._hasFixedClickHandler = true;
        }
        
        // Ensure the button is visible and styled properly
        savePlaylistBtn.style.opacity = '1';
        savePlaylistBtn.style.cursor = 'pointer';
        
        console.log('Save Button Fix: Button fixed, new disabled state:', savePlaylistBtn.disabled);
        
        return true;
    }
    
    // Try to fix as soon as DOM is available
    function init() {
        console.log('Save Button Fix: Initializing');
        
        if (!fixSaveButton()) {
            // If failed, retry after a delay (button might be loaded dynamically)
            console.log('Save Button Fix: Retrying in 500ms');
            setTimeout(fixSaveButton, 500);
            
            // And one more time after a longer delay if needed
            setTimeout(fixSaveButton, 1500);
        }
    }
    
    // Initialize immediately if DOM is already loaded
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        init();
    } else {
        // Otherwise wait for DOM to be ready
        document.addEventListener('DOMContentLoaded', init);
    }
    
    // Also try when window is fully loaded
    window.addEventListener('load', function() {
        console.log('Save Button Fix: Window load event fired');
        fixSaveButton();
    });
})();