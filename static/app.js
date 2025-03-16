document.addEventListener('DOMContentLoaded', function() {
  // Cache DOM elements
  const searchInput = document.getElementById('search-input');
  const searchButton = document.getElementById('search-button');
  const exploreLink = document.getElementById('explore-link');
  const searchResultsList = document.getElementById('search-results-list');
  const exploreList = document.getElementById('explore-list');
  const playlistTracks = document.getElementById('playlist-tracks');
  const numTracksSelect = document.getElementById('num-tracks');
  const regenerateButton = document.getElementById('regenerate-playlist');
  const playlistTitle = document.getElementById('playlist-title');
  
  // Sections
  const welcomeSection = document.getElementById('welcome-section');
  const searchResultsSection = document.getElementById('search-results');
  const exploreSection = document.getElementById('explore-section');
  const playlistSection = document.getElementById('playlist-section');
  
  // Track player elements
  const trackName = document.querySelector('.track-name');
  const trackArtist = document.querySelector('.track-artist');
  
  // Current state
  let currentSeedTrackId = null;
  let currentPlaylistTracks = [];
  
  // Search functionality
  searchButton.addEventListener('click', performSearch);
  searchInput.addEventListener('keypress', function(e) {
    if (e.key === 'Enter') {
      performSearch();
    }
  });
  
  function performSearch() {
    const query = searchInput.value.trim();
    if (query) {
      fetch(`/search?query=${encodeURIComponent(query)}`)
        .then(response => response.json())
        .then(tracks => {
          displaySearchResults(tracks);
        })
        .catch(error => console.error('Error searching tracks:', error));
    }
  }
  
  function displaySearchResults(tracks) {
    searchResultsList.innerHTML = '';
    
    if (tracks.length === 0) {
      searchResultsList.innerHTML = '<p>No tracks found matching your search.</p>';
    } else {
      tracks.forEach(track => {
        const trackCard = createTrackCard(track);
        searchResultsList.appendChild(trackCard);
      });
    }
    
    // Show search results section, hide others
    showSection(searchResultsSection);
  }
  
  // Explore functionality
  exploreLink.addEventListener('click', function(e) {
    e.preventDefault();
    fetchExplore();
  });
  
  function fetchExplore() {
    fetch('/explore')
      .then(response => response.json())
      .then(tracks => {
        displayExplore(tracks);
      })
      .catch(error => console.error('Error getting explore tracks:', error));
  }
  
  function displayExplore(tracks) {
    exploreList.innerHTML = '';
    
    if (tracks.length === 0) {
      exploreList.innerHTML = '<p>No tracks available for exploration. Try adding some music first!</p>';
    } else {
      tracks.forEach(track => {
        const trackCard = createTrackCard(track);
        exploreList.appendChild(trackCard);
      });
    }
    
    // Show explore section, hide others
    showSection(exploreSection);
  }
  
  // Generate playlist functionality
  function generatePlaylist(seedTrackId, numTracks) {
    currentSeedTrackId = seedTrackId;
    
    fetch(`/playlist?seed_track_id=${seedTrackId}&num_tracks=${numTracks}`)
      .then(response => response.json())
      .then(playlist => {
        displayPlaylist(playlist);
      })
      .catch(error => console.error('Error generating playlist:', error));
  }
  
  function displayPlaylist(playlist) {
    currentPlaylistTracks = playlist;
    playlistTracks.innerHTML = '';
    
    if (playlist.length === 0 || playlist.error) {
      playlistTracks.innerHTML = '<p>Error generating playlist. Please try another track.</p>';
    } else {
      // Update playlist title with seed track
      const seedTrack = playlist[0];
      playlistTitle.textContent = `Playlist based on "${seedTrack.title || 'Unknown'}"`;
      
      // Display each track
      playlist.forEach((track, index) => {
        const trackItem = document.createElement('div');
        trackItem.className = 'track-card';
        trackItem.innerHTML = `
          <div class="album-art">
            <i class="fas fa-music"></i>
            <div class="play-overlay">
              <i class="fas fa-play"></i>
            </div>
          </div>
          <div class="track-title">${index + 1}. ${track.title || 'Unknown'}</div>
          <div class="track-artist">${track.artist || 'Unknown Artist'}</div>
          <div class="track-album">${track.album || 'Unknown Album'}</div>
        `;
        
        // When clicking a track in the playlist
        trackItem.addEventListener('click', function() {
          // In a real app, this would play the track
          trackName.textContent = track.title || 'Unknown';
          trackArtist.textContent = track.artist || 'Unknown Artist';
        });
        
        playlistTracks.appendChild(trackItem);
      });
    }
    
    // Show playlist section, hide others
    showSection(playlistSection);
  }
  
  // Regenerate the playlist with potentially different number of tracks
  regenerateButton.addEventListener('click', function() {
    if (currentSeedTrackId) {
      const numTracks = parseInt(numTracksSelect.value);
      generatePlaylist(currentSeedTrackId, numTracks);
    }
  });
  
  // Helper function to create a track card
  function createTrackCard(track) {
    const trackCard = document.createElement('div');
    trackCard.className = 'track-card';
    trackCard.innerHTML = `
      <div class="album-art">
        <i class="fas fa-music"></i>
        <div class="play-overlay">
          <i class="fas fa-play"></i>
        </div>
      </div>
      <div class="track-title">${track.title || 'Unknown'}</div>
      <div class="track-artist">${track.artist || 'Unknown Artist'}</div>
      <div class="track-album">${track.album || 'Unknown Album'}</div>
    `;
    
    // When clicking a track
    trackCard.addEventListener('click', function() {
      // Generate playlist with this track as seed
      const numTracks = parseInt(numTracksSelect.value);
      generatePlaylist(track.id, numTracks);
      
      // Update player bar info
      trackName.textContent = track.title || 'Unknown';
      trackArtist.textContent = track.artist || 'Unknown Artist';
    });
    
    return trackCard;
  }
  
  // Helper function to show a section and hide others
  function showSection(sectionToShow) {
    // Hide all sections
    welcomeSection.style.display = 'none';
    searchResultsSection.style.display = 'none';
    exploreSection.style.display = 'none';
    playlistSection.style.display = 'none';
    
    // Show the requested section
    sectionToShow.style.display = 'block';
  }
  
  // Load explore tracks on initial load
  fetchExplore();
});