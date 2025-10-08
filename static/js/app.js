let bookData = null;
let currentPageIndex = 0;
let currentChapter = {
    title: '',
    content: '',
    word_count: 0,
    segments: []
};
let chapters = [];
let difficultyRanges = {};
let selectedTextSegments = [];
let lastSelectedText = '';

document.addEventListener('DOMContentLoaded', () => {
    loadDifficultyRanges();
    updateDifficultyRange();
});

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
        currentPageIndex = 0;
        chapters = [];
        selectedTextSegments = [];
        currentChapter = { title: '', content: '', word_count: 0, segments: [] };
        
        showBookInfo(data);
        showPage(0);
        updateChapterStats();
        updateChaptersList();
        
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
            <p style="color: #718096;"><strong>Total Pages:</strong> ${data.total_pages}</p>
        </div>
    `;
}

function showPage(index) {
    if (!bookData || !bookData.pages) return;
    
    currentPageIndex = index;
    const page = bookData.pages[index];
    
    const pageDiv = document.getElementById('current-page');
    pageDiv.innerHTML = formatPageWithHighlights(page, index);
    
    document.getElementById('page-info').textContent = `Page ${index + 1} of ${bookData.pages.length}`;
    document.getElementById('prev-btn').disabled = index === 0;
    document.getElementById('next-btn').disabled = index === bookData.pages.length - 1;
}

function formatPageWithHighlights(pageText, pageIndex) {
    const paragraphs = pageText.split('\n\n').filter(p => p.trim());
    return paragraphs.map(para => {
        const trimmedPara = para.trim();
        const highlighted = highlightTextIfSelected(trimmedPara, pageIndex);
        return `<p>${highlighted}</p>`;
    }).join('');
}

function highlightTextIfSelected(text, pageIndex) {
    let result = text;
    
    selectedTextSegments.forEach((segment) => {
        if (segment.pageIndex === pageIndex && text.includes(segment.text)) {
            const colorClass = segment.isFinished 
                ? `highlight-chapter-${segment.chapterIndex % 5}` 
                : 'highlight-current';
            result = result.replace(
                segment.text, 
                `<span class="highlighted ${colorClass}">${segment.text}</span>`
            );
        }
    });
    
    return result;
}

function addSelectedText() {
    const selection = window.getSelection();
    const selectedText = selection.toString().trim();
    
    if (!selectedText) {
        alert('Please select some text first!');
        return;
    }
    
    lastSelectedText = selectedText;
    
    if (currentChapter.content) {
        currentChapter.content += '\n\n' + selectedText;
    } else {
        currentChapter.content = selectedText;
    }
    
    selectedTextSegments.push({
        text: selectedText,
        pageIndex: currentPageIndex,
        isFinished: false,
        chapterIndex: chapters.length
    });
    
    currentChapter.word_count = currentChapter.content.split(/\s+/).filter(w => w.length > 0).length;
    currentChapter.segments = selectedTextSegments.filter(s => !s.isFinished);
    
    updateChapterDisplay();
    updateChapterStats();
    showPage(currentPageIndex);
    
    selection.removeAllRanges();
    showStatus(`Added ${selectedText.split(/\s+/).length} words to chapter`, 'success');
}

function nextPage() {
    if (currentPageIndex < bookData.pages.length - 1) {
        showPage(currentPageIndex + 1);
    }
}

function prevPage() {
    if (currentPageIndex > 0) {
        showPage(currentPageIndex - 1);
    }
}

function addCurrentPageToChapter() {
    if (!bookData) return;
    
    const currentPage = bookData.pages[currentPageIndex];
    
    if (currentChapter.content) {
        currentChapter.content += '\n\n' + currentPage;
    } else {
        currentChapter.content = currentPage;
    }
    
    selectedTextSegments.push({
        text: currentPage,
        pageIndex: currentPageIndex,
        isFinished: false,
        chapterIndex: chapters.length
    });
    
    currentChapter.word_count = currentChapter.content.split(/\s+/).filter(w => w.length > 0).length;
    currentChapter.segments = selectedTextSegments.filter(s => !s.isFinished);
    
    updateChapterDisplay();
    updateChapterStats();
    showPage(currentPageIndex);
    
    if (currentPageIndex < bookData.pages.length - 1) {
        nextPage();
    }
}

function updateChapterDisplay() {
    const contentDiv = document.getElementById('current-chapter-content');
    const paragraphs = currentChapter.content.split('\n\n').filter(p => p.trim());
    contentDiv.innerHTML = paragraphs.map(p => `<p>${p.trim()}</p>`).join('');
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
    
    chapters.push({
        title: title,
        content: currentChapter.content,
        word_count: currentChapter.word_count,
        ignore_validation: ignoreCount
    });
    
    selectedTextSegments.forEach(seg => {
        if (!seg.isFinished) {
            seg.isFinished = true;
            seg.chapterIndex = chapters.length - 1;
        }
    });
    
    currentChapter = { title: '', content: '', word_count: 0, segments: [] };
    document.getElementById('chapter-title').value = `Chapter ${chapters.length + 1}`;
    document.getElementById('ignore-word-count').checked = false;
    
    updateChapterDisplay();
    updateChapterStats();
    updateChaptersList();
    showPage(currentPageIndex);
    
    showStatus(`Chapter "${title}" saved!`, 'success');
}

function clearChapter() {
    if (currentChapter.content && !confirm('Are you sure you want to clear the current chapter?')) {
        return;
    }
    
    selectedTextSegments = selectedTextSegments.filter(s => s.isFinished);
    
    currentChapter = { title: '', content: '', word_count: 0, segments: [] };
    updateChapterDisplay();
    updateChapterStats();
    showPage(currentPageIndex);
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
        const colorClass = `highlight-chapter-${index % 5}`;
        
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
    if (confirm(`Delete "${chapters[index].title}"?`)) {
        chapters.splice(index, 1);
        updateChaptersList();
        showStatus('Chapter deleted', 'info');
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
