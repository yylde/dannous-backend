# Grade-Level Tags Documentation

## Overview
The system generates individual grade-level tags for each book, allowing for precise filtering by grade in the frontend.

## Grade Tag Format
All grade tags follow the format: `grade-{level}`

## Complete List of Grade Tags

### Elementary School
- `grade-K` - Kindergarten
- `grade-1` - First Grade
- `grade-2` - Second Grade  
- `grade-3` - Third Grade
- `grade-4` - Fourth Grade
- `grade-5` - Fifth Grade

### Middle School
- `grade-6` - Sixth Grade
- `grade-7` - Seventh Grade
- `grade-8` - Eighth Grade

### High School
- `grade-9` - Ninth Grade (Freshman)
- `grade-10` - Tenth Grade (Sophomore)
- `grade-11` - Eleventh Grade (Junior)
- `grade-12` - Twelfth Grade (Senior)

## Multi-Grade Books
Books can have **multiple grade tags** if appropriate for multiple grade levels.

**Example:**
A book suitable for 2nd-4th graders will have:
```json
{
  "tags": ["adventure", "fantasy", "grade-2", "grade-3", "grade-4"]
}
```

## Genre Tags
Genre tags are also included alongside grade tags:

### Available Genre Tags
- `adventure`
- `fantasy`
- `mystery`
- `historical-fiction`
- `science-fiction`
- `realistic-fiction`
- `humor`
- `horror`
- `romance`
- `poetry`
- `biography`
- `educational`

## Frontend Filtering Examples

### Filter by Single Grade
```javascript
// Get all books for grade 3
books.filter(book => book.tags.includes('grade-3'))
```

### Filter by Grade Range
```javascript
// Get all books for grades 2-4
const gradeRange = ['grade-2', 'grade-3', 'grade-4'];
books.filter(book => 
  book.tags.some(tag => gradeRange.includes(tag))
)
```

### Filter by Grade AND Genre
```javascript
// Get all adventure books for grade 5
books.filter(book => 
  book.tags.includes('grade-5') && book.tags.includes('adventure')
)
```

### Get All Unique Grade Tags
```javascript
// Extract all unique grade tags from books
const gradeTags = [...new Set(
  books.flatMap(book => book.tags.filter(tag => tag.startsWith('grade-')))
)].sort();
// Result: ["grade-1", "grade-2", "grade-3", ...]
```

## Grade-Specific Questions and Vocabulary

For each detected grade level, the system generates:
- **Questions**: Tailored to the grade's reading comprehension level
- **Vocabulary**: 8 difficulty-appropriate words per grade level

Each question in the database has a `grade_level` column indicating which grade it targets.

Each vocabulary item includes a `grade_level` field in its JSON:
```json
{
  "word": "magnificent",
  "definition": "very beautiful or impressive",
  "example": "The castle was magnificent with tall towers.",
  "grade_level": "grade-4"
}
```

## Database Structure

### draft_questions table
- Has `grade_level` column (VARCHAR(20))
- Stores which grade each question targets

### draft_vocabulary table  
- Vocabulary items include `grade_level` in JSON
- No separate column needed

## Example Book Tags
```json
{
  "id": "123-456",
  "title": "The Magic Tree House",
  "author": "Mary Pope Osborne",
  "tags": [
    "adventure",
    "fantasy",
    "educational",
    "grade-2",
    "grade-3",
    "grade-4"
  ]
}
```

This indicates the book is:
- An adventure/fantasy/educational book
- Appropriate for 2nd, 3rd, and 4th graders
- Has separate questions and vocabulary for each of those grades
