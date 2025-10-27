let bookData = null;
let currentChapter = {
    title: '',
    content: '',
    html_content: '',
    word_count: 0,
    textChunks: [] // Array of {text, html, originalIndices}
};
let chapters = [];
let undoStack = [];
let bookTextParts = []; // Store plain text parts for display
let bookHtmlParts = []; // Store HTML parts for storage
let deletedIndices = new Set(); // Track which indices have been deleted
let currentDraftId = null; // Track current draft
let statusPollingInterval = null; // Track polling interval for chapter status updates
let currentMarkerPosition = null; // Track current marker position
let usedParagraphs = new Set(); // Track which paragraphs have been used in chapters
let usagePollingInterval = null; // Track polling interval for usage updates

// Helper function to escape HTML for use in attributes
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

document.addEventListener('DOMContentLoaded', () => {
    updateDifficultyRange();
    
    // Load drafts in sidebar on page load
    loadDraftsInSidebar();

    // Listen for manual edits to chapter content
    const chapterContent = document.getElementById('current-chapter-content');
    if (chapterContent) {
        chapterContent.addEventListener('input', () => {
            updateChapterFromEditable();
        });
        
        // Handle paste events to preserve HTML formatting
        chapterContent.addEventListener('paste', (e) => {
            e.preventDefault();
            
            // Get the pasted data
            const clipboardData = e.clipboardData || window.clipboardData;
            const htmlData = clipboardData.getData('text/html');
            const textData = clipboardData.getData('text/plain');
            
            // If HTML is available, use it; otherwise use plain text
            const pastedContent = htmlData || textData;
            
            // Insert the content at the cursor position
            const selection = window.getSelection();
            if (selection.rangeCount > 0) {
                const range = selection.getRangeAt(0);
                range.deleteContents();
                
                if (htmlData) {
                    // Create a temporary div to parse the HTML
                    const temp = document.createElement('div');
                    temp.innerHTML = htmlData;
                    const fragment = document.createDocumentFragment();
                    while (temp.firstChild) {
                        fragment.appendChild(temp.firstChild);
                    }
                    range.insertNode(fragment);
                } else {
                    // Plain text
                    const textNode = document.createTextNode(textData);
                    range.insertNode(textNode);
                }
                
                // Move cursor to end of pasted content
                range.collapse(false);
                selection.removeAllRanges();
                selection.addRange(range);
            }
            
            // Update the chapter data
            updateChapterFromEditable();
        });
    }
});

// NEW FUNCTION: Handle text deletion from chapter and restore to book
function handleChapterTextDeletion(oldText, newText) {
    // Find which chunks were removed
    const chunksToRestore = [];

    currentChapter.textChunks.forEach((chunk, idx) => {
        // If this chunk's text is no longer in the new content, restore it
        if (!newText.includes(chunk.text.trim())) {
            chunksToRestore.push(chunk);
        }
    });

    if (chunksToRestore.length === 0) return;

    // Save state for undo
    undoStack.push({
        bookTextParts: [...bookTextParts],
        currentChapter: JSON.parse(JSON.stringify(currentChapter)),
        deletedIndices: new Set(deletedIndices),
        action: 'restore_text'
    });

    // Restore the chunks back to bookTextParts
    chunksToRestore.forEach(chunk => {
        chunk.originalIndices.forEach(index => {
            deletedIndices.delete(index);
        });
    });

    // Rebuild bookTextParts with restored content
    rebuildBookTextParts();

    // Update textChunks to only include remaining chunks
    currentChapter.textChunks = currentChapter.textChunks.filter(chunk =>
        newText.includes(chunk.text.trim())
    );

    // Refresh display
    displayFullBook();
    updateUndoButton();

    showStatus(`Restored ${chunksToRestore.length} text chunk(s) back to book`, 'success');
}

// NEW FUNCTION: Rebuild bookTextParts from original data, excluding deleted indices
function rebuildBookTextParts() {
    if (!bookData) return;

    const originalTextParts = bookData.full_text.split('\n\n').filter(p => p.trim());
    const originalHtmlParts = bookData.full_html.split('\n\n').filter(p => p.trim());
    
    bookTextParts = originalTextParts.filter((part, idx) => !deletedIndices.has(idx));
    bookHtmlParts = originalHtmlParts.filter((part, idx) => !deletedIndices.has(idx));
}

// NEW FUNCTION: Get the indices of selected paragraphs
function getSelectedParagraphIndices(selection) {
    const indices = new Set();

    if (selection.rangeCount === 0) return indices;

    const range = selection.getRangeAt(0);
    const container = document.getElementById('book-text-scroll');

    if (!container) return indices;

    // Get all paragraph elements in the container
    const allParas = container.querySelectorAll('p[data-para-index]');

    // Check which paragraphs are part of the selection
    allParas.forEach(para => {
        if (selection.containsNode(para, true)) {
            const index = parseInt(para.getAttribute('data-para-index'));
            if (!isNaN(index)) {
                indices.add(index);
            }
        }
    });

    return indices;
}

function updateDifficultyRange() {
    const level = document.getElementById('reading-level').value;

    const info = document.getElementById('difficulty-info');
    info.innerHTML = `
        <strong>Selected Level:</strong> ${level.charAt(0).toUpperCase() + level.slice(1)}
    `;

    // Update chapter stats display
    updateChapterStats();
}

// ==================== STATUS POLLING FUNCTIONS ====================

function startStatusPolling() {
    // Clear any existing interval
    stopStatusPolling();
    
    if (!currentDraftId) return;
    
    // Set up polling every 1.5 seconds for more responsive updates
    statusPollingInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/draft-chapters/${currentDraftId}`);
            const data = await response.json();
            
            if (!response.ok) {
                console.error('Failed to fetch chapter statuses:', data.error);
                return;
            }
            
            // Check if any status has changed
            let hasChanges = false;
            let allComplete = true;
            
            data.chapters.forEach(serverChapter => {
                const localChapter = chapters.find(ch => ch.id === serverChapter.id);
                if (localChapter && localChapter.question_status !== serverChapter.question_status) {
                    hasChanges = true;
                    localChapter.question_status = serverChapter.question_status;
                    console.log(`✓ Chapter "${serverChapter.title}" status updated: ${serverChapter.question_status}`);
                }
                
                // Check if any chapter is still generating
                if (serverChapter.question_status === 'generating' || serverChapter.question_status === 'pending') {
                    allComplete = false;
                }
            });
            
            // Update UI if there were changes
            if (hasChanges) {
                console.log('Updating chapters list with new statuses');
                updateChaptersList();
            }
            
            // Stop polling if all chapters are complete (ready or error)
            if (allComplete && data.chapters.length > 0) {
                stopStatusPolling();
                console.log('All chapters complete, stopped polling');
            }
            
        } catch (error) {
            console.error('Error polling chapter status:', error);
        }
    }, 1500);  // Poll every 1.5 seconds for faster per-chapter updates
    
    console.log('Started status polling');
}

function stopStatusPolling() {
    if (statusPollingInterval) {
        clearInterval(statusPollingInterval);
        statusPollingInterval = null;
        console.log('Stopped status polling');
    }
}

async function downloadBook() {
    const gutenbergId = document.getElementById('gutenberg-id').value;

    if (!gutenbergId) {
        showStatus('Please enter a Gutenberg book ID', 'error');
        return;
    }

    showLoading(true);
    showStatus('Downloading book from Project Gutenberg...', 'info');

    try {
        const response = await fetch('/api/download-book', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ gutenberg_id: gutenbergId })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Download failed');
        }

        // Stop any existing polling when loading a new book
        stopStatusPolling();
        
        // Try to save as draft, handle duplicate detection
        bookData = data;
        const draftResponse = await saveDraftAfterDownload();
        
        if (!draftResponse.success) {
            // If it's a duplicate, offer to load the existing draft
            if (draftResponse.status === 409 && draftResponse.existing_draft_id) {
                const loadExisting = confirm(draftResponse.error + '\n\nWould you like to open the existing draft instead?');
                if (loadExisting) {
                    await loadDraft(draftResponse.existing_draft_id);
                    return;
                } else {
                    showStatus('Book download cancelled. Select a different book or continue editing the existing draft.', 'warning');
                    return;
                }
            }
            throw new Error(draftResponse.error || 'Failed to save draft');
        }
        
        // Continue with normal flow
        setupNewBookAfterDownload();

    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

async function saveDraftAfterDownload() {
    try {
        const response = await fetch('/api/draft', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                gutenberg_id: bookData.book_id,
                title: bookData.title,
                author: bookData.author,
                full_text: bookData.full_text,
                full_html: bookData.full_html,
                metadata: bookData.metadata,
                age_range: '6-12',  // Default age range
                reading_level: document.getElementById('reading-level')?.value || 'intermediate',
                genre: 'general'  // Default genre
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            currentDraftId = data.draft_id;
            return { success: true };
        } else {
            return { 
                success: false, 
                error: data.error,
                status: response.status,
                existing_draft_id: data.existing_draft_id
            };
        }
    } catch (error) {
        return { success: false, error: error.message };
    }
}

function setupNewBookAfterDownload() {
    if (!bookData) return;
    
    chapters = [];
    currentChapter = { title: '', content: '', html_content: '', word_count: 0, textChunks: [] };
    undoStack = [];
    deletedIndices = new Set();

    // Initialize book text parts (plain text for display)
    bookTextParts = bookData.full_text.split('\n\n').filter(p => p.trim());
    
    // Initialize book HTML parts (HTML for storage)
    bookHtmlParts = bookData.full_html.split('\n\n').filter(p => p.trim());

    // Clear form values for new book
    document.getElementById('reading-level').value = 'intermediate';
    document.getElementById('cover-image-url').value = '';
    
    // Initialize tags as empty and set status to pending
    currentTags = [];
    renderTags();
    updateTagStatusBadge('pending');
    
    // Start polling for tag status after a short delay (to allow backend to start)
    if (currentDraftId) {
        setTimeout(() => {
            updateTagStatusBadge('generating');
            startTagStatusPolling(currentDraftId);
        }, 1000);
    }
    
    // Show draft info
    document.getElementById('draft-title').textContent = `${bookData.title} by ${bookData.author}`;
    document.getElementById('current-draft-info').style.display = 'block';

    showBookInfo(bookData);
    displayFullBook();
    updateChapterStats();
    updateChaptersList();
    updateUndoButton();
    
    // Refresh sidebar to show new draft
    loadDraftsInSidebar();

    document.getElementById('book-section').style.display = 'block';
    showStatus(`Book loaded and saved as draft: ${bookData.title} by ${bookData.author}`, 'success');
}

function showBookInfo(data) {
    const info = document.getElementById('book-info');
    info.innerHTML = `
        <div style="background: #f7fafc; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
            <h2 style="color: #667eea; margin-bottom: 10px;">${data.title}</h2>
            <p style="color: #718096; margin-bottom: 5px;"><strong>Author:</strong> ${data.author}</p>
            <p style="color: #718096;"><strong>Total Words:</strong> ~${Math.floor(data.full_text.split(' ').length)}</p>
        </div>
    `;
}

function displayFullBook() {
    if (!bookData) return;

    const scrollDiv = document.getElementById('book-text-scroll');

    // Use full_html to display images and formatting
    const originalParts = (bookData.full_html || bookData.full_text).split('\n\n').filter(p => p.trim());

    scrollDiv.innerHTML = originalParts.map((part, idx) => {
        // Skip if this index is deleted
        if (deletedIndices.has(idx)) {
            return '';
        }

        const trimmedPart = part.trim();
        
        // Check if this paragraph has been used in a chapter
        const isUsed = usedParagraphs.has(idx);
        const usedStyle = isUsed ? ' style="background-color: #d4edda; border-left: 3px solid #28a745; padding-left: 8px;"' : '';

        // Check if this is already an HTML tag (heading, paragraph, image, etc.)
        if (trimmedPart.startsWith('<') && trimmedPart.includes('>')) {
            // Add data-para-index to paragraphs for tracking
            if (trimmedPart.startsWith('<p')) {
                return trimmedPart.replace('<p', `<p data-para-index="${idx}"${usedStyle}`);
            }
            return trimmedPart;
        } else {
            // Wrap plain text in paragraph tag
            return `<p data-para-index="${idx}"${usedStyle}>${trimmedPart}</p>`;
        }
    }).join('');
    
    // Set up click listener for marker placement
    setupMarkerClickListener();
    
    // Render existing marker if present
    renderMarker();
}

// ==================== MARKER FUNCTIONS ====================

function setupMarkerClickListener() {
    const scrollDiv = document.getElementById('book-text-scroll');
    if (!scrollDiv) return;
    
    // Remove existing listener if any
    scrollDiv.removeEventListener('click', handleMarkerClick);
    
    // Add click event listener
    scrollDiv.addEventListener('click', handleMarkerClick);
}

function handleMarkerClick(e) {
    // Only place marker if clicking on the book text, not during text selection
    if (window.getSelection().toString().length > 0) {
        return; // User is selecting text, don't place marker
    }
    
    if (!currentDraftId) {
        showStatus('Please save the book first before placing a marker', 'warning');
        return;
    }
    
    const scrollDiv = document.getElementById('book-text-scroll');
    const rect = scrollDiv.getBoundingClientRect();
    
    // Calculate position relative to the scroll container
    const x = e.clientX - rect.left + scrollDiv.scrollLeft;
    const y = e.clientY - rect.top + scrollDiv.scrollTop;
    
    // Find the paragraph that was clicked
    let clickedParagraph = null;
    let paragraphIndex = null;
    
    if (e.target.tagName === 'P' && e.target.hasAttribute('data-para-index')) {
        clickedParagraph = e.target;
        paragraphIndex = parseInt(e.target.getAttribute('data-para-index'));
    } else if (e.target.closest('p[data-para-index]')) {
        clickedParagraph = e.target.closest('p[data-para-index]');
        paragraphIndex = parseInt(clickedParagraph.getAttribute('data-para-index'));
    }
    
    // Store marker position
    currentMarkerPosition = {
        x: x,
        y: y,
        paragraphIndex: paragraphIndex,
        timestamp: new Date().toISOString()
    };
    
    // Save to database
    saveMarkerPosition();
    
    // Render marker
    renderMarker();
    
    showStatus('Marker placed and saved', 'success');
}

async function saveMarkerPosition() {
    if (!currentDraftId || !currentMarkerPosition) return;
    
    try {
        const response = await fetch(`/api/draft/${currentDraftId}/marker`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                marker_position: currentMarkerPosition
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            console.error('Failed to save marker:', data.error);
        }
    } catch (error) {
        console.error('Error saving marker position:', error);
    }
}

function renderMarker() {
    // Remove existing marker if any
    const existingMarker = document.querySelector('.chapter-marker');
    if (existingMarker) {
        existingMarker.remove();
    }
    
    if (!currentMarkerPosition) return;
    
    const scrollDiv = document.getElementById('book-text-scroll');
    if (!scrollDiv) return;
    
    // Create marker element
    const marker = document.createElement('div');
    marker.className = 'chapter-marker';
    marker.title = 'Last position marker';
    
    // Position the marker
    marker.style.left = `${currentMarkerPosition.x}px`;
    marker.style.top = `${currentMarkerPosition.y}px`;
    
    // Add to scroll container
    scrollDiv.appendChild(marker);
}

// ==================== USAGE TRACKING FUNCTIONS ====================

async function fetchUsageData() {
    if (!currentDraftId) return;
    
    try {
        const response = await fetch(`/api/draft/${currentDraftId}/usage`);
        const data = await response.json();
        
        if (response.ok && data.used_paragraphs) {
            // Update usedParagraphs set
            usedParagraphs.clear();
            data.used_paragraphs.forEach(idx => usedParagraphs.add(idx));
            
            // Refresh the book display to show highlighting
            displayFullBook();
        }
    } catch (error) {
        console.error('Error fetching usage data:', error);
    }
}

function startUsagePolling() {
    // Stop any existing polling
    stopUsagePolling();
    
    // Fetch immediately
    fetchUsageData();
    
    // Poll every 5 seconds
    usagePollingInterval = setInterval(fetchUsageData, 5000);
}

function stopUsagePolling() {
    if (usagePollingInterval) {
        clearInterval(usagePollingInterval);
        usagePollingInterval = null;
    }
}

// IMPROVED FUNCTION: Now stores metadata about original indices and HTML
function autoAddSelectedText(selectedText, selectedIndices) {
    if (!bookData) return;

    // Save state for undo
    undoStack.push({
        bookTextParts: [...bookTextParts],
        bookHtmlParts: [...bookHtmlParts],
        currentChapter: JSON.parse(JSON.stringify(currentChapter)),
        deletedIndices: new Set(deletedIndices),
        action: 'add_text'
    });

    // Get corresponding HTML parts for the selected indices
    const originalHtmlParts = bookData.full_html.split('\n\n').filter(p => p.trim());
    const selectedHtmlParts = [];
    selectedIndices.forEach(idx => {
        if (idx < originalHtmlParts.length) {
            selectedHtmlParts.push(originalHtmlParts[idx]);
        }
    });
    const selectedHtml = selectedHtmlParts.join('\n\n');

    // Create a chunk with text, HTML, and original indices
    const chunk = {
        text: selectedText,
        html: selectedHtml,
        originalIndices: Array.from(selectedIndices)
    };

    currentChapter.textChunks.push(chunk);

    // Add to current chapter content (plain text)
    if (currentChapter.content) {
        currentChapter.content += '\n\n' + selectedText;
    } else {
        currentChapter.content = selectedText;
    }

    // Add to current chapter HTML content
    if (currentChapter.html_content) {
        currentChapter.html_content += '\n\n' + selectedHtml;
    } else {
        currentChapter.html_content = selectedHtml;
    }

    // Mark these indices as deleted
    selectedIndices.forEach(idx => deletedIndices.add(idx));

    currentChapter.word_count = currentChapter.content.split(/\s+/).filter(w => w.length > 0).length;

    updateChapterDisplay();
    updateChapterStats();
    displayFullBook();
    updateUndoButton();

    showStatus(`Added ${selectedText.split(/\s+/).length} words to chapter (removed from book text)`, 'success');
}

function undo() {
    if (undoStack.length === 0) {
        showStatus('Nothing to undo', 'info');
        return;
    }

    const previousState = undoStack.pop();

    bookTextParts = previousState.bookTextParts;
    bookHtmlParts = previousState.bookHtmlParts || bookTextParts; // Fallback for old state
    currentChapter = previousState.currentChapter;
    deletedIndices = previousState.deletedIndices;

    updateChapterDisplay();
    updateChapterStats();
    displayFullBook();
    updateUndoButton();

    showStatus('Undo successful', 'success');
}

function updateUndoButton() {
    const undoBtn = document.getElementById('undo-btn');
    if (undoBtn) {
        undoBtn.disabled = undoStack.length === 0;
    }
}

function updateChapterDisplay() {
    const contentDiv = document.getElementById('current-chapter-content');
    const paragraphs = currentChapter.content.split('\n\n').filter(p => p.trim());
    contentDiv.innerHTML = paragraphs.map(p => `<p>${p.trim()}</p>`).join('');
}

function updateChapterFromEditable() {
    const contentDiv = document.getElementById('current-chapter-content');
    const editedText = contentDiv.innerText.trim();
    const editedHtml = contentDiv.innerHTML.trim();

    currentChapter.content = editedText;
    currentChapter.html_content = editedHtml;
    currentChapter.word_count = editedText ? editedText.split(/\s+/).filter(w => w.length > 0).length : 0;

    updateChapterStats();
}

function updateChapterStats() {
    const wordCount = currentChapter.word_count;

    const stats = document.getElementById('chapter-stats');
    stats.innerHTML = `
        <div class="stat-item">
            <span class="stat-value">${wordCount}</span>
            <span class="stat-label">Words</span>
        </div>
    `;
}

async function finishChapter() {
    if (!currentChapter.content) {
        alert('Chapter is empty! Add some content first.');
        return;
    }

    const title = document.getElementById('chapter-title').value || `Chapter ${chapters.length + 1}`;

    // Save state for undo
    undoStack.push({
        bookTextParts: [...bookTextParts],
        currentChapter: JSON.parse(JSON.stringify(currentChapter)),
        chapters: JSON.parse(JSON.stringify(chapters)),
        deletedIndices: new Set(deletedIndices),
        action: 'finish_chapter'
    });

    // Prepare chapter data with both plain text and HTML
    const chapterData = {
        title: title,
        content: currentChapter.content,
        html_content: currentChapter.html_content,
        word_count: currentChapter.word_count,
        textChunks: currentChapter.textChunks,
        question_status: 'generating'
    };
    
    // Save to draft and trigger async question generation
    const chapterId = await saveDraftChapter(chapterData);
    if (chapterId) {
        chapterData.id = chapterId;
    }

    // Save chapter (with metadata)
    chapters.push(chapterData);

    // Reset for next chapter
    currentChapter = { title: '', content: '', html_content: '', word_count: 0, textChunks: [] };
    document.getElementById('chapter-title').value = `Chapter ${chapters.length + 1}`;

    updateChapterDisplay();
    updateChapterStats();
    updateChaptersList();
    updateUndoButton();
    
    // Start polling to track question generation progress
    startStatusPolling();
    
    // Update usage tracking immediately
    fetchUsageData();

    showStatus(`Chapter "${title}" saved! Questions generating...`, 'success');
}

function discardChapter() {
    if (!currentChapter.content) {
        showStatus('Chapter is already empty', 'info');
        return;
    }

    if (!confirm('Discard current chapter content? The text will be restored back to the book.')) {
        return;
    }

    // Save state for undo
    undoStack.push({
        bookTextParts: [...bookTextParts],
        bookHtmlParts: [...bookHtmlParts],
        currentChapter: JSON.parse(JSON.stringify(currentChapter)),
        deletedIndices: new Set(deletedIndices),
        action: 'discard_chapter'
    });

    // Restore all chunks back to the book
    currentChapter.textChunks.forEach(chunk => {
        chunk.originalIndices.forEach(index => {
            deletedIndices.delete(index);
        });
    });

    // Clear the current chapter
    currentChapter = { title: '', content: '', html_content: '', word_count: 0, textChunks: [] };
    document.getElementById('chapter-title').value = `Chapter ${chapters.length + 1}`;

    updateChapterDisplay();
    updateChapterStats();
    displayFullBook();
    updateUndoButton();

    showStatus('Chapter discarded and text restored to book', 'success');
}

function clearChapter() {
    if (currentChapter.content && !confirm('Are you sure you want to clear the current chapter? Text will be restored to book.')) {
        return;
    }

    // Save state for undo
    undoStack.push({
        bookTextParts: [...bookTextParts],
        bookHtmlParts: [...bookHtmlParts],
        currentChapter: JSON.parse(JSON.stringify(currentChapter)),
        deletedIndices: new Set(deletedIndices),
        action: 'clear_chapter'
    });

    // Restore chunks to book
    currentChapter.textChunks.forEach(chunk => {
        chunk.originalIndices.forEach(index => {
            deletedIndices.delete(index);
        });
    });

    currentChapter = { title: '', content: '', html_content: '', word_count: 0, textChunks: [] };
    updateChapterDisplay();
    updateChapterStats();
    displayFullBook();
    updateUndoButton();
}

function updateAllChapterStatusesToGenerating() {
    // Immediately update all chapters to 'generating' status in the UI
    chapters.forEach(chapter => {
        chapter.question_status = 'generating';
    });
    updateChaptersList();
}

function updateChaptersList() {
    const container = document.getElementById('chapters-container');
    document.getElementById('chapter-count').textContent = chapters.length;

    if (chapters.length === 0) {
        container.innerHTML = '<p style="color: #718096; text-align: center;">No chapters yet</p>';
        return;
    }

    container.innerHTML = chapters.map((chapter, index) => {
        // Question status badge
        const questionStatus = chapter.question_status || 'pending';
        const statusBadge = `<span class="status-badge status-${questionStatus}">${questionStatus.toUpperCase()}</span>`;
        
        // Make clickable if has ID (saved to draft)
        const clickHandler = chapter.id ? `onclick="viewChapter('${chapter.id}')" class="chapter-item-clickable"` : '';

        return `
            <div class="chapter-item" style="border-left: 4px solid ${getColorForChapter(index)};" ${clickHandler}>
                <div class="chapter-header">
                    <span class="chapter-title">${chapter.title}</span>
                    ${statusBadge}
                    ${chapter.id ? `<button onclick="event.stopPropagation(); regenerateChapterQuestions('${chapter.id}')" class="btn btn-secondary" style="margin-right: 5px; padding: 4px 8px; font-size: 12px;">🔄 Regen</button>` : ''}
                    <button onclick="event.stopPropagation(); deleteChapter(${index})" class="delete-btn">Delete</button>
                </div>
                <div class="chapter-stats">
                    <span>${chapter.word_count} words</span>
                </div>
                ${chapter.id ? '<div style="font-size: 11px; color: #718096; margin-top: 4px;">Click to view questions</div>' : ''}
            </div>
        `;
    }).join('');
}

function getColorForChapter(index) {
    const colors = ['#667eea', '#48bb78', '#ed8936', '#9f7aea', '#38a169'];
    return colors[index % colors.length];
}

function deleteChapter(index) {
    if (confirm(`Delete "${chapters[index].title}"? The text will be restored back to the book.`)) {
        // Save state for undo
        undoStack.push({
            bookTextParts: [...bookTextParts],
            bookHtmlParts: [...bookHtmlParts],
            currentChapter: JSON.parse(JSON.stringify(currentChapter)),
            chapters: JSON.parse(JSON.stringify(chapters)),
            deletedIndices: new Set(deletedIndices),
            action: 'delete_chapter'
        });

        // Restore the deleted chapter's text back to the book
        const deletedChapter = chapters[index];
        if (deletedChapter.textChunks) {
            deletedChapter.textChunks.forEach(chunk => {
                chunk.originalIndices.forEach(idx => {
                    deletedIndices.delete(idx);
                });
            });
        }

        // Remove the chapter
        chapters.splice(index, 1);

        updateChaptersList();
        displayFullBook();
        updateUndoButton();
        showStatus('Chapter deleted and text restored to book', 'info');
    }
}

async function generateAITitle() {
    if (!currentChapter.content) {
        alert('Add some content to the chapter first!');
        return;
    }

    showLoading(true);

    try {
        const response = await fetch('/api/generate-title', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: currentChapter.content })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Title generation failed');
        }

        document.getElementById('chapter-title').value = data.title;
        showStatus(`AI generated title: "${data.title}"`, 'success');

    } catch (error) {
        showStatus(`Error generating title: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

async function saveChapters() {
    if (chapters.length === 0) {
        alert('No chapters to save! Create at least one chapter first.');
        return;
    }

    if (currentChapter.content) {
        const saveCurrentFirst = confirm('You have unsaved work in the current chapter. Save it first?');
        if (saveCurrentFirst) {
            finishChapter();
        }
    }

    const ageRange = '8-12'; // Default age range
    const readingLevel = document.getElementById('reading-level').value;

    showLoading(true);
    showStatus('Saving chapters and generating questions...', 'info');

    try {
        const response = await fetch('/api/save-chapters', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chapters: chapters,
                metadata: bookData.metadata,
                age_range: ageRange,
                reading_level: readingLevel
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Save failed');
        }

        showStatus(
            `Success! Saved ${data.chapters_saved} chapters and generated ${data.questions_generated} questions. Book ID: ${data.book_id}`,
            'success'
        );

        setTimeout(() => {
            if (confirm('Book saved successfully! Do you want to process another book?')) {
                location.reload();
            }
        }, 2000);

    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

function showLoading(show) {
    document.getElementById('loading').style.display = show ? 'flex' : 'none';
}

function showStatus(message, type = 'info') {
    const statusDiv = document.getElementById('download-status');
    const alertClass = type === 'error' ? 'alert-error' : type === 'success' ? 'alert-success' : 'alert-info';

    statusDiv.innerHTML = `<div class="alert ${alertClass}">${message}</div>`;

    if (type === 'success' || type === 'info') {
        setTimeout(() => {
            statusDiv.innerHTML = '';
        }, 5000);
    }
}

// ==================== DRAFT FUNCTIONS ====================

function showNewBookForm() {
    document.getElementById('download-section').scrollIntoView({ behavior: 'smooth' });
    document.getElementById('gutenberg-id').focus();
}

async function loadDraftsInSidebar() {
    try {
        const response = await fetch('/api/drafts');
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Failed to load drafts');
        }
        
        const container = document.getElementById('drafts-list-sidebar');
        
        if (data.drafts.length === 0) {
            container.innerHTML = '<p style="color: #718096; text-align: center; padding: 20px; font-size: 14px;">No books yet.<br>Click "+ New" to start!</p>';
        } else {
            container.innerHTML = data.drafts.map(draft => {
                const statusClass = draft.is_completed ? 'completed' : 'in-progress';
                const statusText = draft.is_completed ? 'Completed' : 'In Progress';
                return `
                    <div class="draft-item ${currentDraftId === draft.id ? 'active' : ''}" onclick="loadDraft('${draft.id}')">
                        <button class="delete-draft-btn" onclick="deleteDraft('${draft.id}', event)" title="Delete this book">
                            &times;
                        </button>
                        <h4>${draft.title}</h4>
                        <p><strong>${draft.author}</strong></p>
                        <p>${draft.chapter_count || 0} chapters</p>
                        <span class="draft-status ${statusClass}">${statusText}</span>
                    </div>
                `;
            }).join('');
        }
    } catch (error) {
        console.error('Error loading drafts:', error);
        const container = document.getElementById('drafts-list-sidebar');
        container.innerHTML = '<p style="color: #e53e3e; text-align: center; padding: 20px; font-size: 14px;">Error loading books</p>';
    }
}

async function deleteDraft(draftId, event) {
    if (event) {
        event.stopPropagation();
    }
    
    if (!confirm('Are you sure you want to delete this book? This action cannot be undone.')) {
        return;
    }
    
    try {
        showLoading(true);
        
        const response = await fetch(`/api/draft/${draftId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Failed to delete draft');
        }
        
        // If we just deleted the currently open draft, clear the UI
        if (currentDraftId === draftId) {
            currentDraftId = null;
            bookData = null;
            chapters = [];
            currentTags = [];
            usedParagraphs.clear();
            stopUsagePolling();
            stopTagStatusPolling();
            stopDescriptionStatusPolling();
            document.getElementById('book-section').style.display = 'none';
            document.getElementById('current-draft-info').style.display = 'none';
        }
        
        // Force refresh the sidebar list
        console.log('Draft deleted, refreshing sidebar...');
        await loadDraftsInSidebar();
        
        showStatus('Book deleted successfully', 'success');
    } catch (error) {
        console.error('Error deleting draft:', error);
        showStatus(`Error deleting book: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

async function loadDraft(draftId) {
    try {
        showLoading(true);
        
        const response = await fetch(`/api/draft/${draftId}`);
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Failed to load draft');
        }
        
        // Set current draft
        currentDraftId = draftId;
        const draft = data.draft;
        
        // Set book data
        bookData = {
            book_id: draft.gutenberg_id,
            title: draft.title,
            author: draft.author,
            full_text: draft.full_text,
            full_html: draft.full_html || draft.full_text,
            metadata: draft.metadata
        };
        
        // Initialize book text parts (plain text for display)
        bookTextParts = draft.full_text.split('\n\n').filter(p => p.trim());
        
        // Initialize book HTML parts (HTML for storage)
        bookHtmlParts = (draft.full_html || draft.full_text).split('\n\n').filter(p => p.trim());
        
        // Load chapters
        chapters = draft.chapters.map(ch => ({
            id: ch.id,
            title: ch.title,
            content: ch.content,
            word_count: ch.word_count,
            question_status: ch.question_status
        }));
        
        // Mark deleted indices based on chapters
        deletedIndices = new Set();
        chapters.forEach(ch => {
            const content = ch.content;
            bookTextParts.forEach((part, idx) => {
                if (content.includes(part)) {
                    deletedIndices.add(idx);
                }
            });
        });
        
        // Set form values
        document.getElementById('reading-level').value = draft.reading_level || 'intermediate';
        document.getElementById('cover-image-url').value = draft.cover_image_url || '';
        updateCoverPreview(); // Show preview if URL exists
        
        // Load tags and tag status
        currentTags = draft.tags || [];
        console.log('Draft loaded - Tags:', currentTags, 'Status:', draft.tag_status);
        renderTags();
        updateTagStatusBadge(draft.tag_status);
        
        // Start tag status polling if generating
        if (draft.tag_status === 'pending' || draft.tag_status === 'generating') {
            console.log('Starting tag status polling...');
            startTagStatusPolling(draftId);
        }
        
        // Load description and description status
        const descriptionDiv = document.getElementById('book-description');
        descriptionDiv.textContent = draft.description || '';
        console.log('Draft loaded - Description status:', draft.description_status);
        updateDescriptionStatusBadge(draft.description_status);
        
        // Start description status polling if generating
        if (draft.description_status === 'pending' || draft.description_status === 'generating') {
            console.log('Starting description status polling...');
            startDescriptionStatusPolling(draftId);
        }
        
        // Load marker position if available
        currentMarkerPosition = draft.last_marker_position || null;
        
        // Show draft info
        document.getElementById('draft-title').textContent = `${draft.title} by ${draft.author}`;
        document.getElementById('current-draft-info').style.display = 'block';
        
        // Update UI
        showBookInfo(bookData);
        displayFullBook();
        updateChaptersList();
        updateChapterStats();
        
        document.getElementById('book-section').style.display = 'block';
        
        // Refresh sidebar to show active draft
        loadDraftsInSidebar();
        
        // Start polling for chapter status updates
        startStatusPolling();
        
        // Start polling for usage tracking
        startUsagePolling();
        
        showStatus(`Loaded draft: ${draft.title}`, 'success');
        
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

async function saveDraft() {
    if (!bookData) return null;
    
    try {
        const ageRange = '8-12'; // Default age range
        const readingLevel = document.getElementById('reading-level').value;
        let coverImageUrl = document.getElementById('cover-image-url').value.trim();
        
        // If cover URL is empty and we're creating a new draft, ask user
        if (!coverImageUrl && !currentDraftId) {
            const addCover = confirm('Would you like to add a book cover URL?\n\nClick OK to add one now, or Cancel to skip.');
            if (addCover) {
                const url = prompt('Enter the book cover image URL:');
                if (url && url.trim()) {
                    coverImageUrl = url.trim();
                    document.getElementById('cover-image-url').value = coverImageUrl;
                }
            }
        }
        
        const response = await fetch('/api/draft', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                draft_id: currentDraftId,
                gutenberg_id: bookData.book_id,
                title: bookData.title,
                author: bookData.author,
                full_text: bookData.full_text,
                full_html: bookData.full_html,
                age_range: ageRange,
                reading_level: readingLevel,
                cover_image_url: coverImageUrl,
                metadata: bookData.metadata
            })
        });
        
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to save draft');
        }
        
        currentDraftId = data.draft_id;
        return currentDraftId;
        
    } catch (error) {
        console.error('Error saving draft:', error);
        return null;
    }
}

async function saveDraftChapter(chapterData) {
    if (!currentDraftId) {
        await saveDraft();
    }
    
    if (!currentDraftId) {
        showStatus('Failed to save draft', 'error');
        return null;
    }
    
    try {
        const ageRange = '8-12'; // Default age range
        const readingLevel = document.getElementById('reading-level').value;
        
        const response = await fetch('/api/draft-chapter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                draft_id: currentDraftId,
                chapter_number: chapters.length + 1,
                title: chapterData.title,
                content: chapterData.content,
                html_content: chapterData.html_content,
                word_count: chapterData.word_count,
                age_range: ageRange,
                reading_level: readingLevel
            })
        });
        
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to save chapter');
        }
        
        return data.chapter_id;
        
    } catch (error) {
        console.error('Error saving draft chapter:', error);
        showStatus(`Error: ${error.message}`, 'error');
        return null;
    }
}

async function viewChapter(chapterId) {
    try {
        showLoading(true);
        
        const response = await fetch(`/api/draft-chapter/${chapterId}`);
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Failed to load chapter');
        }
        
        const chapter = data.chapter;
        
        // Build modal content
        let modalHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <h2 id="chapter-title-${chapter.id}" style="margin: 0;">${chapter.title}</h2>
                <button id="edit-chapter-btn-${chapter.id}" onclick="toggleEditChapter('${chapter.id}')" class="edit-btn">Edit Chapter</button>
            </div>
            <p><strong>Word Count:</strong> ${chapter.word_count}</p>
            <p><strong>Status:</strong> <span class="status-badge status-${chapter.question_status}">${chapter.question_status.toUpperCase()}</span></p>
            <hr style="margin: 20px 0;">
        `;
        
        if (chapter.html_formatting) {
            modalHTML += `
                <h3>Chapter Content</h3>
                <div id="chapter-content-${chapter.id}" class="chapter-html-content">${chapter.html_formatting}</div>
                <hr style="margin: 20px 0;">
            `;
        } else if (chapter.content) {
            modalHTML += `
                <h3>Chapter Content</h3>
                <div id="chapter-content-${chapter.id}" class="chapter-html-content">${chapter.content.replace(/\n\n/g, '</p><p>').replace(/^/, '<p>').replace(/$/, '</p>')}</div>
                <hr style="margin: 20px 0;">
            `;
        }
        
        if (chapter.question_status === 'pending' || chapter.question_status === 'generating') {
            modalHTML += `<p style="color: #718096;">Questions are being generated...</p>`;
        } else if (chapter.question_status === 'error') {
            modalHTML += `<p style="color: #e53e3e;">Error generating questions. Please try again.</p>`;
        } else if (chapter.question_status === 'ready') {
            // Group questions by grade level
            const questionsByGrade = {};
            if (chapter.questions && chapter.questions.length > 0) {
                chapter.questions.forEach(q => {
                    const grade = q.grade_level || 'unspecified';
                    if (!questionsByGrade[grade]) {
                        questionsByGrade[grade] = [];
                    }
                    questionsByGrade[grade].push(q);
                });
            }
            
            // Display questions and vocabulary grouped by grade
            const grades = Object.keys(questionsByGrade).sort();
            
            if (grades.length > 0) {
                grades.forEach(grade => {
                    const gradeLabel = grade.replace('grade-', 'Grade ');
                    modalHTML += `<h3 style="margin-top: 30px; color: #2d3748;">${gradeLabel}</h3>`;
                    
                    // Show questions for this grade
                    const questions = questionsByGrade[grade];
                    modalHTML += `<div style="margin-bottom: 20px;">`;
                    modalHTML += `<h4 style="color: #4a5568; margin-bottom: 10px;">Questions:</h4>`;
                    questions.forEach((q, i) => {
                        const keywordsStr = escapeHtml(JSON.stringify(q.expected_keywords || []));
                        const questionTextEscaped = escapeHtml(q.question_text || '');
                        const questionTypeEscaped = escapeHtml(q.question_type || '');
                        const difficultyEscaped = escapeHtml(q.difficulty_level || '');
                        
                        modalHTML += `
                            <div class="question-item" id="question-container-${q.id}" style="margin-bottom: 15px; padding: 10px; background: #f7fafc; border-radius: 5px;">
                                <div style="display: flex; justify-content: space-between; align-items: start;">
                                    <div style="flex: 1;">
                                        <strong>Q${i + 1}:</strong> 
                                        <span id="q-text-${q.id}" 
                                              data-original="${questionTextEscaped}"
                                              data-type="${questionTypeEscaped}"
                                              data-difficulty="${difficultyEscaped}"
                                              data-keywords="${keywordsStr}"
                                              data-min="${q.min_word_count}"
                                              data-max="${q.max_word_count}"
                                              style="display: inline;">${q.question_text}</span>
                                        <div id="q-meta-${q.id}" style="margin-top: 5px; font-size: 12px; color: #718096;">
                                            <em>Type: <span id="q-type-${q.id}" data-original="${questionTypeEscaped}">${q.question_type}</span> | 
                                            Difficulty: <span id="q-diff-${q.id}" data-original="${difficultyEscaped}">${q.difficulty_level}</span></em>
                                        </div>
                                    </div>
                                    <div style="margin-left: 10px; white-space: nowrap;">
                                        <button id="edit-q-btn-${q.id}" onclick="toggleEditQuestion('${q.id}', '${chapterId}')" class="edit-btn" style="margin-right: 5px;">Edit</button>
                                        <button onclick="deleteQuestionItem('${q.id}', '${chapterId}')" class="delete-btn">Delete</button>
                                    </div>
                                </div>
                            </div>
                        `;
                    });
                    modalHTML += `</div>`;
                    
                    // Show vocabulary for this grade (filter by grade_level)
                    const gradeVocab = (chapter.vocabulary || []).filter(v => v.grade_level === grade);
                    
                    if (gradeVocab.length > 0) {
                        modalHTML += `<div style="margin-top: 20px;">`;
                        modalHTML += `<h4 style="color: #4a5568; margin-bottom: 10px;">Vocabulary:</h4>`;
                        gradeVocab.forEach(v => {
                            const wordEscaped = escapeHtml(v.word || '');
                            const defEscaped = escapeHtml(v.definition || '');
                            const exEscaped = escapeHtml(v.example || '');
                            
                            modalHTML += `
                                <div class="vocab-item" id="vocab-container-${v.id}" style="margin-bottom: 15px; padding: 10px; background: #f7fafc; border-radius: 5px;">
                                    <div style="display: flex; justify-content: space-between; align-items: start;">
                                        <div style="flex: 1;">
                                            <div id="v-word-${v.id}" class="vocab-word" data-original="${wordEscaped}" style="font-weight: bold; color: #2d3748;">${v.word}</div>
                                            <div id="v-def-${v.id}" class="vocab-definition" data-original="${defEscaped}" style="margin-top: 5px; color: #4a5568;">${v.definition}</div>
                                            <div id="v-ex-${v.id}" class="vocab-example" data-original="${exEscaped}" style="margin-top: 5px; font-style: italic; color: #718096;">${v.example ? `"${v.example}"` : ''}</div>
                                        </div>
                                        <div style="margin-left: 10px; white-space: nowrap;">
                                            <button id="edit-v-btn-${v.id}" onclick="toggleEditVocabulary('${v.id}', '${chapterId}')" class="edit-btn" style="margin-right: 5px;">Edit</button>
                                            <button onclick="deleteVocabularyItem('${v.id}', '${chapterId}')" class="delete-btn">Delete</button>
                                        </div>
                                    </div>
                                </div>
                            `;
                        });
                        modalHTML += `</div>`;
                    }
                });
            }
        }
        
        document.getElementById('chapter-detail-content').innerHTML = modalHTML;
        document.getElementById('chapter-modal').style.display = 'flex';
        
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

function getEditingItems() {
    // Get all items currently in edit mode
    const modal = document.getElementById('chapter-modal');
    if (!modal) return { questions: [], vocabulary: [] };
    
    const questions = [];
    const vocabulary = [];
    
    // Find all Save buttons (indicates edit mode)
    const saveBtns = modal.querySelectorAll('.save-btn');
    saveBtns.forEach(btn => {
        const id = btn.id;
        if (id.startsWith('edit-q-btn-')) {
            const questionId = id.replace('edit-q-btn-', '');
            questions.push(questionId);
        } else if (id.startsWith('edit-v-btn-')) {
            const vocabId = id.replace('edit-v-btn-', '');
            vocabulary.push(vocabId);
        }
    });
    
    return { questions, vocabulary };
}

async function closeChapterModal() {
    const editing = getEditingItems();
    const hasEdits = editing.questions.length > 0 || editing.vocabulary.length > 0;
    
    // Check for unsaved edits
    if (hasEdits) {
        const userChoice = confirm('You have unsaved changes. Do you want to save them?\n\nOK = Save and close\nCancel = Don\'t save and close');
        
        if (userChoice) {
            // User wants to save - get the chapter ID from the modal
            const chapterIdElem = document.querySelector('[id^="question-container-"], [id^="vocab-container-"]');
            if (!chapterIdElem) {
                document.getElementById('chapter-modal').style.display = 'none';
                return;
            }
            
            // Extract chapter ID from any save button's onclick attribute
            const anyBtn = document.querySelector('.save-btn');
            let chapterId = null;
            if (anyBtn) {
                const onclickStr = anyBtn.getAttribute('onclick') || '';
                const match = onclickStr.match(/'([^']+)'/g);
                if (match && match.length >= 2) {
                    chapterId = match[1].replace(/'/g, '');
                }
            }
            
            if (!chapterId) {
                showStatus('Could not determine chapter ID', 'error');
                document.getElementById('chapter-modal').style.display = 'none';
                return;
            }
            
            // Save all questions
            for (const qId of editing.questions) {
                await saveQuestion(qId, chapterId);
            }
            
            // Save all vocabulary
            for (const vId of editing.vocabulary) {
                await saveVocabulary(vId, chapterId);
            }
        }
        // If user clicked Cancel, we don't save but still close
    }
    
    document.getElementById('chapter-modal').style.display = 'none';
}

function toggleEditQuestion(questionId, chapterId) {
    const textElem = document.getElementById(`q-text-${questionId}`);
    const typeElem = document.getElementById(`q-type-${questionId}`);
    const diffElem = document.getElementById(`q-diff-${questionId}`);
    const btn = document.getElementById(`edit-q-btn-${questionId}`);
    
    if (!textElem || !btn) return;
    
    // Check if currently in edit mode
    if (textElem.contentEditable === 'true') {
        // Save mode
        saveQuestion(questionId, chapterId);
    } else {
        // Edit mode - CSS will handle the styling via [contenteditable="true"]
        textElem.contentEditable = 'true';
        typeElem.contentEditable = 'true';
        diffElem.contentEditable = 'true';
        
        btn.textContent = 'Save';
        btn.classList.remove('edit-btn');
        btn.classList.add('save-btn');
        
        textElem.focus();
    }
}

async function saveQuestion(questionId, chapterId) {
    const textElem = document.getElementById(`q-text-${questionId}`);
    const typeElem = document.getElementById(`q-type-${questionId}`);
    const diffElem = document.getElementById(`q-diff-${questionId}`);
    const btn = document.getElementById(`edit-q-btn-${questionId}`);
    
    const questionText = textElem.innerText.trim();
    const questionType = typeElem.innerText.trim();
    const difficulty = diffElem.innerText.trim();
    
    if (!questionText) {
        showStatus('Question text cannot be empty', 'error');
        return;
    }
    
    try {
        showLoading(true);
        
        const keywords = JSON.parse(textElem.dataset.keywords || '[]');
        const minWords = parseInt(textElem.dataset.min) || 20;
        const maxWords = parseInt(textElem.dataset.max) || 200;
        
        const response = await fetch(`/api/question/${questionId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question_text: questionText,
                question_type: questionType,
                difficulty_level: difficulty,
                expected_keywords: keywords,
                min_word_count: minWords,
                max_word_count: maxWords
            })
        });
        
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to update question');
        }
        
        // Exit edit mode
        textElem.contentEditable = 'false';
        typeElem.contentEditable = 'false';
        diffElem.contentEditable = 'false';
        
        btn.textContent = 'Edit';
        btn.classList.remove('save-btn');
        btn.classList.add('edit-btn');
        
        // Update data attributes
        textElem.dataset.original = questionText;
        typeElem.dataset.original = questionType;
        diffElem.dataset.original = difficulty;
        
        showStatus('Question updated successfully', 'success');
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

async function deleteQuestionItem(questionId, chapterId) {
    if (!confirm('Are you sure you want to delete this question?')) return;
    
    try {
        showLoading(true);
        const response = await fetch(`/api/question/${questionId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to delete question');
        }
        
        showStatus('Question deleted successfully', 'success');
        viewChapter(chapterId); // Reload the view
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

function toggleEditVocabulary(vocabId, chapterId) {
    const wordElem = document.getElementById(`v-word-${vocabId}`);
    const defElem = document.getElementById(`v-def-${vocabId}`);
    const exElem = document.getElementById(`v-ex-${vocabId}`);
    const btn = document.getElementById(`edit-v-btn-${vocabId}`);
    
    if (!wordElem || !btn) return;
    
    // Check if currently in edit mode
    if (wordElem.contentEditable === 'true') {
        // Save mode
        saveVocabulary(vocabId, chapterId);
    } else {
        // Edit mode
        wordElem.contentEditable = 'true';
        defElem.contentEditable = 'true';
        exElem.contentEditable = 'true';
        
        wordElem.style.backgroundColor = '#fff';
        wordElem.style.padding = '5px';
        wordElem.style.borderRadius = '3px';
        wordElem.style.border = '1px solid #cbd5e0';
        
        defElem.style.backgroundColor = '#fff';
        defElem.style.padding = '5px';
        defElem.style.borderRadius = '3px';
        defElem.style.border = '1px solid #cbd5e0';
        
        exElem.style.backgroundColor = '#fff';
        exElem.style.padding = '5px';
        exElem.style.borderRadius = '3px';
        exElem.style.border = '1px solid #cbd5e0';
        
        btn.textContent = 'Save';
        btn.classList.remove('edit-btn');
        btn.classList.add('save-btn');
        
        wordElem.focus();
    }
}

async function saveVocabulary(vocabId, chapterId) {
    const wordElem = document.getElementById(`v-word-${vocabId}`);
    const defElem = document.getElementById(`v-def-${vocabId}`);
    const exElem = document.getElementById(`v-ex-${vocabId}`);
    const btn = document.getElementById(`edit-v-btn-${vocabId}`);
    
    const word = wordElem.innerText.trim();
    const definition = defElem.innerText.trim();
    const example = exElem.innerText.trim().replace(/^"|"$/g, ''); // Remove quotes if present
    
    if (!word) {
        showStatus('Word cannot be empty', 'error');
        return;
    }
    
    if (!definition) {
        showStatus('Definition cannot be empty', 'error');
        return;
    }
    
    try {
        showLoading(true);
        const response = await fetch(`/api/vocabulary/${vocabId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                word: word,
                definition: definition,
                example: example
            })
        });
        
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to update vocabulary');
        }
        
        // Exit edit mode
        wordElem.contentEditable = 'false';
        defElem.contentEditable = 'false';
        exElem.contentEditable = 'false';
        
        wordElem.style.backgroundColor = '';
        wordElem.style.padding = '';
        wordElem.style.border = '';
        defElem.style.backgroundColor = '';
        defElem.style.padding = '';
        defElem.style.border = '';
        exElem.style.backgroundColor = '';
        exElem.style.padding = '';
        exElem.style.border = '';
        
        btn.textContent = 'Edit';
        btn.classList.remove('save-btn');
        btn.classList.add('edit-btn');
        
        // Update display
        wordElem.dataset.original = word;
        defElem.dataset.original = definition;
        exElem.dataset.original = example;
        exElem.innerHTML = example ? `"${example}"` : '';
        
        showStatus('Vocabulary updated successfully', 'success');
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

async function deleteVocabularyItem(vocabId, chapterId) {
    if (!confirm('Are you sure you want to delete this vocabulary item?')) return;
    
    try {
        showLoading(true);
        const response = await fetch(`/api/vocabulary/${vocabId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to delete vocabulary');
        }
        
        showStatus('Vocabulary deleted successfully', 'success');
        viewChapter(chapterId); // Reload the view
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

function toggleEditChapter(chapterId) {
    const contentElem = document.getElementById(`chapter-content-${chapterId}`);
    const titleElem = document.getElementById(`chapter-title-${chapterId}`);
    const btn = document.getElementById(`edit-chapter-btn-${chapterId}`);
    
    if (!contentElem || !btn) return;
    
    // Check if currently in edit mode
    if (contentElem.contentEditable === 'true') {
        // Save mode
        saveChapter(chapterId);
    } else {
        // Edit mode
        contentElem.contentEditable = 'true';
        titleElem.contentEditable = 'true';
        
        contentElem.style.backgroundColor = '#fff';
        contentElem.style.padding = '10px';
        contentElem.style.borderRadius = '5px';
        contentElem.style.border = '2px solid #667eea';
        
        titleElem.style.backgroundColor = '#fff';
        titleElem.style.padding = '5px';
        titleElem.style.borderRadius = '3px';
        titleElem.style.border = '2px solid #667eea';
        
        btn.textContent = 'Save Chapter';
        btn.classList.remove('edit-btn');
        btn.classList.add('save-btn');
        
        titleElem.focus();
    }
}

async function saveChapter(chapterId) {
    const contentElem = document.getElementById(`chapter-content-${chapterId}`);
    const titleElem = document.getElementById(`chapter-title-${chapterId}`);
    const btn = document.getElementById(`edit-chapter-btn-${chapterId}`);
    
    const newTitle = titleElem.innerText.trim();
    const newContent = contentElem.innerText.trim();
    const newHtml = contentElem.innerHTML;
    
    if (!newTitle) {
        showStatus('Chapter title cannot be empty', 'error');
        return;
    }
    
    if (!newContent) {
        showStatus('Chapter content cannot be empty', 'error');
        return;
    }
    
    try {
        showLoading(true);
        
        const response = await fetch(`/api/chapter/${chapterId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: newTitle,
                content: newContent,
                html_formatting: newHtml
            })
        });
        
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to update chapter');
        }
        
        // Exit edit mode
        contentElem.contentEditable = 'false';
        titleElem.contentEditable = 'false';
        
        contentElem.style.backgroundColor = '';
        contentElem.style.padding = '';
        contentElem.style.border = '';
        titleElem.style.backgroundColor = '';
        titleElem.style.padding = '';
        titleElem.style.border = '';
        
        btn.textContent = 'Edit Chapter';
        btn.classList.remove('save-btn');
        btn.classList.add('edit-btn');
        
        // Update usage tracking immediately
        fetchUsageData();
        
        showStatus('Chapter updated successfully', 'success');
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

async function finalizeBook() {
    if (!currentDraftId) {
        showStatus('No draft to finalize', 'error');
        return;
    }
    
    if (chapters.length === 0) {
        showStatus('Please add at least one chapter before finalizing', 'error');
        return;
    }
    
    if (!confirm('Are you ready to finalize this book? This will move it to the main books table.')) {
        return;
    }
    
    // Stop polling before finalizing
    stopStatusPolling();
    
    try {
        showLoading(true);
        showStatus('Finalizing book...', 'info');
        
        const response = await fetch(`/api/finalize-draft/${currentDraftId}`, {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Finalization failed');
        }
        
        showStatus(
            `Success! Book finalized with ${data.chapters} chapters and ${data.questions} questions. Book ID: ${data.book_id}`,
            'success'
        );
        
        setTimeout(() => {
            if (confirm('Book finalized successfully! Do you want to process another book?')) {
                location.reload();
            }
        }, 2000);
        
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

function showReadingInfoModal() {
    const modal = document.getElementById('reading-info-modal');
    if (modal) {
        modal.style.display = 'flex';
    }
}

function closeReadingInfoModal() {
    const modal = document.getElementById('reading-info-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const readingModal = document.getElementById('reading-info-modal');
        const chapterModal = document.getElementById('chapter-modal');
        
        if (readingModal && readingModal.style.display === 'flex') {
            closeReadingInfoModal();
        }
        
        if (chapterModal && chapterModal.style.display === 'flex') {
            closeChapterModal();
        }
    }
});

document.addEventListener('click', (e) => {
    const readingModal = document.getElementById('reading-info-modal');
    const chapterModal = document.getElementById('chapter-modal');
    
    if (readingModal && e.target === readingModal) {
        closeReadingInfoModal();
    }
    
    if (chapterModal && e.target === chapterModal) {
        closeChapterModal();
    }
});

// ==================== TAG MANAGEMENT ====================

let currentTags = [];
let tagStatusPollingInterval = null;
let descriptionStatusPollingInterval = null;

function showAddTagInput() {
    document.getElementById('add-tag-input-container').style.display = 'flex';
    document.getElementById('new-tag-input').focus();
}

function hideAddTagInput() {
    document.getElementById('add-tag-input-container').style.display = 'none';
    document.getElementById('new-tag-input').value = '';
}

function handleTagKeyPress(event) {
    if (event.key === 'Enter') {
        event.preventDefault();
        addNewTag();
    }
}

function addNewTag() {
    const input = document.getElementById('new-tag-input');
    const tagValue = input.value.trim().toLowerCase();
    
    if (!tagValue) {
        return;
    }
    
    if (currentTags.includes(tagValue)) {
        showStatus('Tag already exists', 'error');
        return;
    }
    
    currentTags.push(tagValue);
    renderTags();
    hideAddTagInput();
}

function removeTag(tag) {
    currentTags = currentTags.filter(t => t !== tag);
    renderTags();
}

function renderTags() {
    const container = document.getElementById('tags-container');
    container.innerHTML = '';
    
    currentTags.forEach(tag => {
        const tagChip = document.createElement('div');
        tagChip.className = 'tag-chip';
        tagChip.innerHTML = `
            ${tag}
            <span class="remove-tag" onclick="removeTag('${tag}')">&times;</span>
        `;
        container.appendChild(tagChip);
    });
    
    const addChip = document.createElement('div');
    addChip.className = 'tag-chip add-tag-chip';
    addChip.textContent = '+ Add Tag';
    addChip.onclick = showAddTagInput;
    container.appendChild(addChip);
}

function updateTagStatusBadge(status) {
    const badge = document.getElementById('tag-status-badge');
    
    if (!status || status === 'ready') {
        badge.style.display = 'none';
        return;
    }
    
    badge.style.display = 'inline-block';
    badge.className = 'tag-status-badge ' + status;
    
    const statusText = {
        'pending': 'Pending',
        'generating': 'Generating...',
        'error': 'Error'
    };
    
    badge.textContent = statusText[status] || status;
}

async function saveTagsAndUrl() {
    if (!currentDraftId) {
        showStatus('No draft selected', 'error');
        return;
    }
    
    try {
        const coverUrl = document.getElementById('cover-image-url').value.trim();
        
        showLoading(true);
        showStatus('Saving tags and cover URL...', 'info');
        
        const response = await fetch(`/api/draft-tags-url/${currentDraftId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                tags: currentTags,
                cover_image_url: coverUrl
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Failed to save');
        }
        
        showStatus('Tags and cover URL saved successfully! Regenerating questions...', 'success');
        
        // Update cover preview after saving
        updateCoverPreview();
        
        // Immediately update all chapter statuses to "generating" in the UI
        updateAllChapterStatusesToGenerating();
        
        // Automatically trigger question regeneration after saving tags
        setTimeout(async () => {
            try {
                showStatus('Regenerating questions based on grade tags...', 'info');
                
                const regenResponse = await fetch(`/api/draft/${currentDraftId}/regenerate-questions`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                
                const regenData = await regenResponse.json();
                
                if (!regenResponse.ok) {
                    throw new Error(regenData.error || 'Failed to regenerate questions');
                }
                
                showStatus('Question regeneration started! Updating chapters...', 'success');
                
                // Wait a bit then refresh to get backend status
                setTimeout(() => {
                    startStatusPolling();
                }, 500);
                
            } catch (regenError) {
                showStatus(`Error regenerating questions: ${regenError.message}`, 'error');
            } finally {
                showLoading(false);
            }
        }, 500);
        
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
        showLoading(false);
    }
}

async function generateDescription() {
    if (!currentDraftId) {
        showStatus('No draft selected', 'error');
        return;
    }
    
    try {
        showLoading(true);
        showStatus('Generating book description with AI...', 'info');
        
        // Trigger description generation
        const response = await fetch(`/api/draft/${currentDraftId}/generate-description`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            // Handle 409 Conflict specifically (description generation already in progress)
            if (response.status === 409) {
                showStatus('Description generation is already in progress. Please wait...', 'warning');
                return;
            }
            throw new Error(data.error || 'Failed to generate description');
        }
        
        showStatus('Description generation started! AI is analyzing the book...', 'success');
        
        // Start polling for description status
        startDescriptionStatusPolling(currentDraftId);
        
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

async function regenerateQuestions() {
    if (!currentDraftId) {
        showStatus('No draft selected', 'error');
        return;
    }
    
    try {
        showLoading(true);
        
        // First, save the current tags
        showStatus('Saving tags...', 'info');
        const coverUrl = document.getElementById('cover-image-url').value.trim();
        
        const saveResponse = await fetch(`/api/draft-tags-url/${currentDraftId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                tags: currentTags,
                cover_image_url: coverUrl
            })
        });
        
        if (!saveResponse.ok) {
            const saveData = await saveResponse.json();
            throw new Error(saveData.error || 'Failed to save tags');
        }
        
        // Then trigger question regeneration
        showStatus('Regenerating questions for grade changes...', 'info');
        
        // Immediately update all chapter statuses to "generating" in the UI
        updateAllChapterStatusesToGenerating();
        
        const regenResponse = await fetch(`/api/draft/${currentDraftId}/regenerate-questions`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const regenData = await regenResponse.json();
        
        if (!regenResponse.ok) {
            throw new Error(regenData.error || 'Failed to regenerate questions');
        }
        
        showStatus('Question regeneration started! Updating chapters...', 'success');
        
        // Start polling for chapter status updates
        startStatusPolling();
        
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

async function regenerateChapterQuestions(chapterId) {
    if (!currentDraftId) {
        showStatus('No draft selected', 'error');
        return;
    }
    
    try {
        showLoading(true);
        showStatus('Regenerating questions for this chapter...', 'info');
        
        // Update this chapter's status to "generating" in the UI
        const chapter = chapters.find(ch => ch.id === chapterId);
        if (chapter) {
            chapter.question_status = 'generating';
            updateChaptersList();
        }
        
        const response = await fetch(`/api/chapter/${chapterId}/regenerate-questions`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            // Handle 409 Conflict specifically (question generation already in progress)
            if (response.status === 409) {
                showStatus('Question generation is already in progress for this chapter. Please wait...', 'warning');
                return;
            }
            throw new Error(data.error || 'Failed to regenerate questions');
        }
        
        showStatus('Question regeneration started for chapter!', 'success');
        
        // Start polling for chapter status updates
        startStatusPolling();
        
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

async function regenerateTags() {
    if (!currentDraftId) {
        showStatus('No draft selected', 'error');
        return;
    }
    
    try {
        showLoading(true);
        showStatus('Regenerating tags with AI...', 'info');
        
        // Trigger tag regeneration
        const response = await fetch(`/api/draft/${currentDraftId}/regenerate-tags`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            // Handle 409 Conflict specifically (tag generation already in progress)
            if (response.status === 409) {
                showStatus('Tag generation is already in progress. Please wait...', 'warning');
                return;
            }
            throw new Error(data.error || 'Failed to regenerate tags');
        }
        
        showStatus('Tag regeneration started! AI is analyzing the book...', 'success');
        
        // Start polling for tag status and auto-trigger question regeneration when done
        startTagStatusPollingWithAutoRegen(currentDraftId);
        
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

function startTagStatusPollingWithAutoRegen(draftId) {
    // Always stop existing polling first to prevent dangling intervals
    stopTagStatusPolling();
    
    console.log('Started tag status polling with auto-regen for draft:', draftId);
    
    tagStatusPollingInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/draft/${draftId}`);
            const data = await response.json();
            
            if (data.success && data.draft) {
                const tagStatus = data.draft.tag_status;
                console.log('Tag status:', tagStatus);
                updateTagStatusBadge(tagStatus);
                
                if (tagStatus === 'ready') {
                    if (data.draft.tags && data.draft.tags.length > 0) {
                        currentTags = data.draft.tags;
                        renderTags();
                        console.log('✓ Tags loaded:', currentTags);
                        stopTagStatusPolling();
                        showStatus('Tags generated successfully! Now regenerating questions...', 'success');
                        
                        // Auto-trigger question regeneration after a brief delay
                        setTimeout(() => {
                            triggerQuestionRegenAfterTags();
                        }, 1000);
                    } else {
                        console.warn('⚠ Tag status is ready but no tags returned');
                        stopTagStatusPolling();
                        showStatus('Tags generated but empty. Please add tags manually.', 'warning');
                    }
                } else if (tagStatus === 'error') {
                    stopTagStatusPolling();
                    console.error('✗ Tag generation failed - check if Ollama is running');
                    showStatus('Tag generation failed. Check if Ollama is running, or add tags manually.', 'error');
                }
            }
        } catch (error) {
            console.error('Tag status polling error:', error);
        }
    }, 2000);
}

async function triggerQuestionRegenAfterTags() {
    try {
        showLoading(true);
        showStatus('Regenerating questions based on new tags...', 'info');
        
        // Immediately update all chapter statuses to "generating" in the UI
        updateAllChapterStatusesToGenerating();
        
        const response = await fetch(`/api/draft/${currentDraftId}/regenerate-questions`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Failed to regenerate questions');
        }
        
        showStatus('Question regeneration started! Updating all chapters...', 'success');
        
        // Start polling for chapter status updates
        startStatusPolling();
        
        // Refresh the draft to show updated data
        await loadDraft(currentDraftId);
        
    } catch (error) {
        showStatus(`Error regenerating questions: ${error.message}`, 'error');
        showLoading(false);
    }
}

function startTagStatusPolling(draftId) {
    if (tagStatusPollingInterval) {
        clearInterval(tagStatusPollingInterval);
    }
    
    console.log('Started tag status polling for draft:', draftId);
    
    tagStatusPollingInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/draft/${draftId}`);
            const data = await response.json();
            
            if (data.success && data.draft) {
                const tagStatus = data.draft.tag_status;
                console.log('Tag status:', tagStatus);
                updateTagStatusBadge(tagStatus);
                
                if (tagStatus === 'ready') {
                    if (data.draft.tags && data.draft.tags.length > 0) {
                        currentTags = data.draft.tags;
                        renderTags();
                        console.log('✓ Tags loaded:', currentTags);
                        stopTagStatusPolling();
                        showStatus('Tags generated successfully!', 'success');
                    } else {
                        console.warn('⚠ Tag status is ready but no tags returned');
                        stopTagStatusPolling();
                    }
                } else if (tagStatus === 'error') {
                    stopTagStatusPolling();
                    console.error('✗ Tag generation failed - check if Ollama is running');
                    showStatus('Tag generation failed. Check if Ollama is running, or add tags manually.', 'error');
                }
            }
        } catch (error) {
            console.error('Tag status polling error:', error);
        }
    }, 2000);
}

function stopTagStatusPolling() {
    if (tagStatusPollingInterval) {
        clearInterval(tagStatusPollingInterval);
        tagStatusPollingInterval = null;
    }
}

// ==================== DESCRIPTION STATUS POLLING ====================

function startDescriptionStatusPolling(draftId) {
    // Always stop existing polling first to prevent dangling intervals
    stopDescriptionStatusPolling();
    
    console.log('Started description status polling for draft:', draftId);
    
    descriptionStatusPollingInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/draft/${draftId}`);
            const data = await response.json();
            
            if (data.success && data.draft) {
                const descriptionStatus = data.draft.description_status;
                console.log('Description status:', descriptionStatus);
                updateDescriptionStatusBadge(descriptionStatus);
                
                if (descriptionStatus === 'ready') {
                    if (data.draft.description) {
                        const descriptionDiv = document.getElementById('book-description');
                        descriptionDiv.textContent = data.draft.description;
                        console.log('✓ Description loaded');
                        stopDescriptionStatusPolling();
                        showStatus('Description generated successfully!', 'success');
                    } else {
                        console.warn('⚠ Description status is ready but no description returned');
                        stopDescriptionStatusPolling();
                        showStatus('Description generated but empty.', 'warning');
                    }
                } else if (descriptionStatus === 'error') {
                    stopDescriptionStatusPolling();
                    console.error('✗ Description generation failed - check if Ollama is running');
                    showStatus('Description generation failed. Check if Ollama is running.', 'error');
                }
            }
        } catch (error) {
            console.error('Description status polling error:', error);
        }
    }, 2000);
}

function stopDescriptionStatusPolling() {
    if (descriptionStatusPollingInterval) {
        clearInterval(descriptionStatusPollingInterval);
        descriptionStatusPollingInterval = null;
    }
}

function updateDescriptionStatusBadge(status) {
    const badge = document.getElementById('description-status-badge');
    if (!badge) return;
    
    badge.className = 'status-badge';
    
    if (status === 'pending' || status === 'generating') {
        badge.classList.add('status-generating');
        badge.textContent = status === 'pending' ? '⏳ Pending' : '⚙️ Generating';
        badge.style.display = 'inline-block';
    } else if (status === 'ready') {
        badge.classList.add('status-ready');
        badge.textContent = '✓ Ready';
        badge.style.display = 'inline-block';
    } else if (status === 'error') {
        badge.classList.add('status-error');
        badge.textContent = '✗ Error';
        badge.style.display = 'inline-block';
    } else {
        badge.style.display = 'none';
    }
}

function updateCoverPreview() {
    const urlInput = document.getElementById('cover-image-url');
    const previewContainer = document.getElementById('cover-preview-container');
    const previewImg = document.getElementById('cover-preview-img');
    
    // Check if elements exist
    if (!urlInput || !previewContainer || !previewImg) {
        console.warn('Cover preview elements not found');
        return;
    }
    
    const url = urlInput.value ? urlInput.value.trim() : '';
    
    // Show preview if URL is not empty and looks valid
    if (url && url.length > 0) {
        console.log('Setting cover preview URL:', url);
        previewImg.src = url;
        previewContainer.style.display = 'block';
    } else {
        console.log('Hiding cover preview - no URL');
        hideCoverPreview();
    }
}

function hideCoverPreview() {
    const previewContainer = document.getElementById('cover-preview-container');
    if (previewContainer) {
        previewContainer.style.display = 'none';
    }
}