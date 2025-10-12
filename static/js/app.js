let bookData = null;
let currentChapter = {
    title: '',
    content: '',
    word_count: 0,
    textChunks: [] // Array of {text, originalIndices}
};
let chapters = [];
let difficultyRanges = {};
let undoStack = [];
let bookTextParts = []; // Store the book text parts separately
let deletedIndices = new Set(); // Track which indices have been deleted

document.addEventListener('DOMContentLoaded', () => {
    loadDifficultyRanges();
    updateDifficultyRange();

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

    const originalParts = bookData.full_text.split('\n\n').filter(p => p.trim());
    bookTextParts = originalParts.filter((part, idx) => !deletedIndices.has(idx));
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

function updateChapterLegend() {
    const legendItems = document.getElementById('legend-items');
    if (!legendItems) return;

    const colors = [
        { color: '#667eea', label: 'Purple' },
        { color: '#48bb78', label: 'Green' },
        { color: '#ed8936', label: 'Orange' },
        { color: '#9f7aea', label: 'Violet' },
        { color: '#38a169', label: 'Teal' }
    ];

    if (chapters.length === 0) {
        legendItems.innerHTML = '<p style="color: #a0aec0; font-size: 12px; font-style: italic; margin: 0;">No chapters yet</p>';
        return;
    }

    legendItems.innerHTML = chapters.map((chapter, idx) => {
        const colorInfo = colors[idx % 5];
        return `
            <div class="chapter-legend-item">
                <div class="chapter-legend-color" style="background: ${colorInfo.color}; border-left: 3px solid ${colorInfo.color};"></div>
                <span class="chapter-legend-label">Ch ${idx + 1}: ${chapter.title.substring(0, 12)}${chapter.title.length > 12 ? '...' : ''}</span>
            </div>
        `;
    }).join('');
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

        bookData = data;
        chapters = [];
        currentChapter = { title: '', content: '', word_count: 0, textChunks: [] };
        undoStack = [];
        deletedIndices = new Set();

        // Initialize book text parts
        bookTextParts = bookData.full_text.split('\n\n').filter(p => p.trim());

        showBookInfo(data);
        displayFullBook();
        updateChapterStats();
        updateChaptersList();
        updateChapterLegend();
        updateUndoButton();

        document.getElementById('book-section').style.display = 'block';
        showStatus(`Book loaded: ${data.title} by ${data.author}`, 'success');

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

// IMPROVED FUNCTION: Now stores metadata about original indices
function autoAddSelectedText(selectedText, selectedIndices) {
    if (!bookData) return;

    // Save state for undo
    undoStack.push({
        bookTextParts: [...bookTextParts],
        currentChapter: JSON.parse(JSON.stringify(currentChapter)),
        deletedIndices: new Set(deletedIndices),
        action: 'add_text'
    });

    // Create a chunk with text and original indices
    const chunk = {
        text: selectedText,
        originalIndices: Array.from(selectedIndices)
    };

    currentChapter.textChunks.push(chunk);

    // Add to current chapter content
    if (currentChapter.content) {
        currentChapter.content += '\n\n' + selectedText;
    } else {
        currentChapter.content = selectedText;
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

function finishChapter() {
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

    // Save chapter (with metadata)
    chapters.push({
        title: title,
        content: currentChapter.content,
        word_count: currentChapter.word_count,
        ignore_validation: ignoreCount,
        textChunks: currentChapter.textChunks // Save the chunks metadata
    });

    // Reset for next chapter
    currentChapter = { title: '', content: '', word_count: 0, textChunks: [] };
    document.getElementById('chapter-title').value = `Chapter ${chapters.length + 1}`;
    document.getElementById('ignore-word-count').checked = false;

    updateChapterDisplay();
    updateChapterStats();
    updateChaptersList();
    updateChapterLegend();
    updateUndoButton();

    showStatus(`Chapter "${title}" saved!`, 'success');
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
    currentChapter = { title: '', content: '', word_count: 0, textChunks: [] };
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

    currentChapter = { title: '', content: '', word_count: 0, textChunks: [] };
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

        return `
            <div class="chapter-item" style="border-left: 4px solid ${getColorForChapter(index)};">
                <div class="chapter-header">
                    <span class="chapter-title">${chapter.title}</span>
                    <button onclick="deleteChapter(${index})" class="delete-btn">Delete</button>
                </div>
                <div class="chapter-stats">
                    <span style="color: ${statusColor};">${chapter.word_count} words</span>
                    <span>${chapter.ignore_validation ? '✓ Validation ignored' : (isValid ? '✓ Valid' : '✗ Out of range')}</span>
                </div>
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
        updateChapterLegend();
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