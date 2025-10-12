let bookData = null;
let currentChapter = {
    title: '',
    content: '',
    html_content: '',
    word_count: 0,
    textChunks: [] // Array of {text, html, originalIndices}
};
let chapters = [];
let difficultyRanges = {};
let undoStack = [];
let bookTextParts = []; // Store plain text parts for display
let bookHtmlParts = []; // Store HTML parts for storage
let deletedIndices = new Set(); // Track which indices have been deleted
let currentDraftId = null; // Track current draft
let statusPollingInterval = null; // Track polling interval for chapter status updates

document.addEventListener('DOMContentLoaded', () => {
    loadDifficultyRanges();
    updateDifficultyRange();
    
    // Load drafts in sidebar on page load
    loadDraftsInSidebar();

    // Auto-add selected text from book
    document.addEventListener('mouseup', (e) => {
        // Only auto-add if selection is from the book text area
        const bookTextArea = document.getElementById('book-text-scroll');
        if (bookTextArea && bookTextArea.contains(e.target)) {
            setTimeout(() => {
                const selection = window.getSelection();
                const selectedText = selection.toString().trim();

                if (selectedText && selectedText.length > 10) { // Only add if meaningful text
                    // Get the selected paragraphs indices
                    const selectedIndices = getSelectedParagraphIndices(selection);
                    autoAddSelectedText(selectedText, selectedIndices);
                    selection.removeAllRanges();
                }
            }, 100);
        }
    });

    // Listen for manual edits to chapter content - NOW HANDLES DELETIONS
    const chapterContent = document.getElementById('current-chapter-content');
    if (chapterContent) {
        let previousContent = chapterContent.innerText.trim();

        chapterContent.addEventListener('input', () => {
            const currentContent = chapterContent.innerText.trim();

            // Check if text was deleted
            if (currentContent.length < previousContent.length) {
                handleChapterTextDeletion(previousContent, currentContent);
            }

            previousContent = currentContent;
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

async function loadDifficultyRanges() {
    try {
        const response = await fetch('/api/difficulty-ranges');
        difficultyRanges = await response.json();
    } catch (error) {
        console.error('Failed to load difficulty ranges:', error);
    }
}

function updateDifficultyRange() {
    const level = document.getElementById('reading-level').value;
    const range = difficultyRanges[level] || { min: 500, max: 1500 };

    const info = document.getElementById('difficulty-info');
    info.innerHTML = `
        <strong>${level.charAt(0).toUpperCase() + level.slice(1)} Level:</strong> 
        Recommended chapter word count: ${range.min} - ${range.max} words
    `;

    // Update chapter stats to reflect new target range
    updateChapterStats();
}

// ==================== STATUS POLLING FUNCTIONS ====================

function startStatusPolling() {
    // Clear any existing interval
    stopStatusPolling();
    
    if (!currentDraftId) return;
    
    // Set up polling every 3 seconds
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
                }
                
                // Check if any chapter is still generating
                if (serverChapter.question_status === 'generating' || serverChapter.question_status === 'pending') {
                    allComplete = false;
                }
            });
            
            // Update UI if there were changes
            if (hasChanges) {
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
    }, 3000);
    
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
        
        bookData = data;
        chapters = [];
        currentChapter = { title: '', content: '', html_content: '', word_count: 0, textChunks: [] };
        undoStack = [];
        deletedIndices = new Set();

        // Initialize book text parts (plain text for display)
        bookTextParts = bookData.full_text.split('\n\n').filter(p => p.trim());
        
        // Initialize book HTML parts (HTML for storage)
        bookHtmlParts = bookData.full_html.split('\n\n').filter(p => p.trim());

        // Clear form values for new book
        document.getElementById('age-range').value = '8-12';
        document.getElementById('reading-level').value = 'intermediate';
        document.getElementById('genre').value = 'fiction';
        document.getElementById('cover-image-url').value = '';  // Clear cover URL for new book
        
        // Auto-save as draft
        await saveDraft();
        
        // Show draft info
        document.getElementById('draft-title').textContent = `${data.title} by ${data.author}`;
        document.getElementById('current-draft-info').style.display = 'block';

        showBookInfo(data);
        displayFullBook();
        updateChapterStats();
        updateChaptersList();
        updateUndoButton();
        
        // Refresh sidebar to show new draft
        loadDraftsInSidebar();

        document.getElementById('book-section').style.display = 'block';
        showStatus(`Book loaded and saved as draft: ${data.title} by ${data.author}`, 'success');

    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
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

    // Get original parts and filter out deleted ones
    const originalParts = bookData.full_text.split('\n\n').filter(p => p.trim());

    scrollDiv.innerHTML = originalParts.map((part, idx) => {
        // Skip if this index is deleted
        if (deletedIndices.has(idx)) {
            return '';
        }

        const trimmedPart = part.trim();

        // Check if this is a heading tag
        if (trimmedPart.startsWith('<h') && trimmedPart.includes('>')) {
            return trimmedPart;
        } else {
            return `<p data-para-index="${idx}">${trimmedPart}</p>`;
        }
    }).join('');
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

    currentChapter.content = editedText;
    currentChapter.word_count = editedText ? editedText.split(/\s+/).filter(w => w.length > 0).length : 0;

    updateChapterStats();
}

function updateChapterStats() {
    const level = document.getElementById('reading-level').value;
    const range = difficultyRanges[level] || { min: 500, max: 1500 };
    const ignoreCount = document.getElementById('ignore-word-count')?.checked || false;

    const wordCount = currentChapter.word_count;
    const isValid = ignoreCount || (wordCount >= range.min && wordCount <= range.max);
    const validClass = isValid ? 'valid' : 'invalid';

    const stats = document.getElementById('chapter-stats');
    stats.innerHTML = `
        <div class="stat-item">
            <span class="stat-value ${validClass}">${wordCount}</span>
            <span class="stat-label">Words</span>
        </div>
        <div class="stat-item">
            <span class="stat-value">${ignoreCount ? 'N/A' : `${range.min} - ${range.max}`}</span>
            <span class="stat-label">Target Range</span>
        </div>
        <div class="stat-item">
            <span class="stat-value ${validClass}">${ignoreCount ? '✓ Ignored' : (isValid ? '✓ Valid' : '✗ Out of Range')}</span>
            <span class="stat-label">Status</span>
        </div>
    `;
}

async function finishChapter() {
    if (!currentChapter.content) {
        alert('Chapter is empty! Add some content first.');
        return;
    }

    const title = document.getElementById('chapter-title').value || `Chapter ${chapters.length + 1}`;
    const ignoreCount = document.getElementById('ignore-word-count')?.checked || false;

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
        ignore_validation: ignoreCount,
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
    document.getElementById('ignore-word-count').checked = false;

    updateChapterDisplay();
    updateChapterStats();
    updateChaptersList();
    updateUndoButton();
    
    // Start polling to track question generation progress
    startStatusPolling();

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
    document.getElementById('ignore-word-count').checked = false;

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

function updateChaptersList() {
    const container = document.getElementById('chapters-container');
    document.getElementById('chapter-count').textContent = chapters.length;

    if (chapters.length === 0) {
        container.innerHTML = '<p style="color: #718096; text-align: center;">No chapters yet</p>';
        return;
    }

    container.innerHTML = chapters.map((chapter, index) => {
        const level = document.getElementById('reading-level').value;
        const range = difficultyRanges[level] || { min: 500, max: 1500 };
        const isValid = chapter.ignore_validation || (chapter.word_count >= range.min && chapter.word_count <= range.max);
        const statusColor = isValid ? '#48bb78' : '#f56565';
        
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
                    <button onclick="event.stopPropagation(); deleteChapter(${index})" class="delete-btn">Delete</button>
                </div>
                <div class="chapter-stats">
                    <span style="color: ${statusColor};">${chapter.word_count} words</span>
                    <span>${chapter.ignore_validation ? '✓ Validation ignored' : (isValid ? '✓ Valid' : '✗ Out of range')}</span>
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

    const ageRange = document.getElementById('age-range').value;
    const readingLevel = document.getElementById('reading-level').value;
    const genre = document.getElementById('genre').value;

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
                reading_level: readingLevel,
                genre: genre
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
        document.getElementById('age-range').value = draft.age_range || '8-12';
        document.getElementById('reading-level').value = draft.reading_level || 'intermediate';
        document.getElementById('genre').value = draft.genre || 'fiction';
        document.getElementById('cover-image-url').value = draft.cover_image_url || '';
        
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
        const ageRange = document.getElementById('age-range').value;
        const readingLevel = document.getElementById('reading-level').value;
        const genre = document.getElementById('genre').value;
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
                genre: genre,
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
        const ageRange = document.getElementById('age-range').value;
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
            <h2>${chapter.title}</h2>
            <p><strong>Word Count:</strong> ${chapter.word_count}</p>
            <p><strong>Status:</strong> <span class="status-badge status-${chapter.question_status}">${chapter.question_status.toUpperCase()}</span></p>
            <hr style="margin: 20px 0;">
        `;
        
        if (chapter.html_formatting) {
            modalHTML += `
                <h3>Chapter Content</h3>
                <div class="chapter-html-content">${chapter.html_formatting}</div>
                <hr style="margin: 20px 0;">
            `;
        }
        
        if (chapter.question_status === 'pending' || chapter.question_status === 'generating') {
            modalHTML += `<p style="color: #718096;">Questions are being generated...</p>`;
        } else if (chapter.question_status === 'error') {
            modalHTML += `<p style="color: #e53e3e;">Error generating questions. Please try again.</p>`;
        } else if (chapter.question_status === 'ready') {
            // Show vocabulary
            if (chapter.vocabulary && chapter.vocabulary.length > 0) {
                modalHTML += `<h3>Vocabulary</h3>`;
                chapter.vocabulary.forEach(v => {
                    modalHTML += `
                        <div class="vocab-item">
                            <div class="vocab-word">${v.word}</div>
                            <div class="vocab-definition">${v.definition}</div>
                            ${v.example ? `<div class="vocab-example">"${v.example}"</div>` : ''}
                        </div>
                    `;
                });
            }
            
            // Show questions
            if (chapter.questions && chapter.questions.length > 0) {
                modalHTML += `<h3>Questions</h3>`;
                chapter.questions.forEach((q, i) => {
                    modalHTML += `
                        <div class="question-item">
                            <strong>Q${i + 1}:</strong> ${q.question_text}
                            <div style="margin-top: 5px; font-size: 12px; color: #718096;">
                                <em>Difficulty: ${q.difficulty_level}</em>
                            </div>
                        </div>
                    `;
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

function closeChapterModal() {
    document.getElementById('chapter-modal').style.display = 'none';
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