// Debug Script for save-playlist button
console.log('Debug script loaded for save-playlist button');

document.addEventListener('DOMContentLoaded', function() {
  console.log('DOM loaded, looking for save-playlist button');
  const savePlaylistBtn = document.getElementById('save-playlist-btn');
  
  if (savePlaylistBtn) {
    console.log('Found Save Playlist button, attaching event listener');
    
    // Force remove disabled attribute
    savePlaylistBtn.removeAttribute('disabled');
    
    // Add direct click event listener
    savePlaylistBtn.addEventListener('click', function(e) {
      e.preventDefault();
      console.log('Save playlist button clicked');
      
      // Get playlist name from input or modal
      let playlistName = '';
      const playlistNameInput = document.getElementById('playlist-name');
      
      if (playlistNameInput && playlistNameInput.value.trim()) {
        playlistName = playlistNameInput.value.trim();
      } else {
        playlistName = prompt('Enter a name for this playlist:');
        if (!playlistName) return; // User cancelled
      }
      
      console.log('Attempting to save playlist:', playlistName);
      
      // Get tracks from currentPlaylist
      let tracks = [];
      
      // Try different sources for the tracks
      if (window.currentPlaylist && window.currentPlaylist.length) {
        console.log('Using window.currentPlaylist');
        tracks = window.currentPlaylist.map(track => track.id || track);
      } else if (window.playerManager) {
        console.log('Using playerManager.getQueue()');
        const queue = window.playerManager.getQueue();
        if (queue && queue.length) {
          tracks = queue.map(track => track.id || track);
        }
      }
      
      console.log('Tracks to save:', tracks);
      
      if (tracks.length === 0) {
        console.error('No tracks to save');
        alert('There are no tracks to save');
        return;
      }
      
      // Send save playlist request to server - USING CORRECT ENDPOINT
      fetch('/api/playlists', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          name: playlistName,
          description: '',
          tracks: tracks
        })
      })
      .then(response => {
        if (!response.ok) {
          throw new Error(`Server returned ${response.status}: ${response.statusText}`);
        }
        return response.json();
      })
      .then(data => {
        console.log('Save playlist response:', data);
        if (data.success || data.id) {
          alert('Playlist saved successfully!');
          // Optionally close modal if it exists
          const modal = document.getElementById('save-playlist-modal');
          if (modal && typeof modal.close === 'function') {
            modal.close();
          } else if (modal && modal.style) {
            modal.style.display = 'none';
          }
          
          // Reload playlists in sidebar
          if (typeof window.loadSidebarPlaylists === 'function') {
            window.loadSidebarPlaylists();
          } else if (typeof window.loadPlaylists === 'function') {
            window.loadPlaylists();
          }
        } else {
          alert('Error saving playlist: ' + (data.error || 'Unknown error'));
        }
      })
      .catch(error => {
        console.error('Error saving playlist:', error);
        alert('Error saving playlist: ' + error.message);
      });
    });
    
    console.log('Save playlist button initialized');
  } else {
    console.warn('Save Playlist button not found in DOM');
  }
});
