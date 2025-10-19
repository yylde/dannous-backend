# Model Compatibility Guide

This system is designed to work with **ANY Ollama model** - whether it's a thinking model (like DeepSeek-R1) or a standard model (like Llama, Mistral, Gemma).

## Supported Model Types

### ✅ Thinking Models (Reasoning Models)
Models that output `<think>...</think>` tags showing their reasoning process:
- **DeepSeek-R1** series (1.5B - 671B)
- **QwQ-32B** (Qwen reasoning model)
- **Thinking models from Ollama library**

**What the system does:**
- Automatically detects and removes thinking tags
- Extracts JSON from the answer section
- Works without `format='json'` to preserve thinking capability

### ✅ Standard Models
Models that directly output responses without thinking tags:
- **Llama** (all versions)
- **Mistral** (all versions)
- **Gemma** (all versions)
- **Phi** (all versions)
- **Any other Ollama model**

**What the system does:**
- Tries free-form output first (2 attempts)
- Falls back to `format='json'` if parsing fails
- Robust JSON extraction handles various formats

## How It Works

### Intelligent Retry Strategy
The system uses a 3-attempt strategy:

1. **Attempt 1: Free-form** (supports thinking models)
   - No format constraints
   - Allows model to think and reason
   - Parses JSON after removing thinking tags

2. **Attempt 2: Free-form retry** (in case of temporary issues)
   - Same as attempt 1
   - Exponential backoff between attempts

3. **Attempt 3: JSON format** (for standard models)
   - Uses `format='json'` parameter
   - Forces JSON output from model
   - Disables thinking mode

### Automatic Detection
The system automatically:
- ✅ Detects thinking tags in responses
- ✅ Removes thinking content before parsing
- ✅ Extracts JSON using multiple methods
- ✅ Logs diagnostic information for debugging
- ✅ Provides detailed error messages

## Changing Models

### Via Configuration File
Edit `src/config.py`:
```python
ollama_model: str = "deepseek-r1:7b"  # Change to any model
```

### Supported Model Examples
```python
# Thinking models
ollama_model: str = "deepseek-r1:7b"
ollama_model: str = "qwq:32b"

# Standard models
ollama_model: str = "llama3.2:3b"
ollama_model: str = "mistral:7b"
ollama_model: str = "gemma2:9b"
ollama_model: str = "phi3:mini"
```

### Via Environment Variable
Set the `OLLAMA_MODEL` environment variable:
```bash
export OLLAMA_MODEL="llama3.2:3b"
python app.py
```

## Response Format Examples

### Thinking Model Response
```
<think>
Let me analyze this book...
The vocabulary seems appropriate for grades 3-5.
I should include words like "magnificent" and "peculiar".
</think>

{"questions":[{"text":"Why did...","keywords":["character"],"difficulty":"medium"}],"vocabulary":[{"word":"magnificent","definition":"very beautiful","example":"The castle was magnificent."}]}
```

### Standard Model Response
```json
{"questions":[{"text":"Why did...","keywords":["character"],"difficulty":"medium"}],"vocabulary":[{"word":"magnificent","definition":"very beautiful","example":"The castle was magnificent."}]}
```

**Both formats work perfectly!** The system handles them automatically.

## Troubleshooting

### Model not generating valid JSON?
The system will:
1. Try 3 times with different strategies
2. Fall back to generic questions if all attempts fail
3. Log detailed error messages to help diagnose issues

### Check the logs:
```bash
# Look for diagnostic information
grep "Model:" /tmp/logs/Server_*.log
grep "Success with" /tmp/logs/Server_*.log
grep "Contains thinking tags" /tmp/logs/Server_*.log
```

### Common Issues

**Issue: Model outputs thinking tags but no JSON**
- **Solution:** The system automatically removes thinking tags and extracts JSON

**Issue: JSON parsing fails repeatedly**
- **Solution:** Check if the model is installed: `ollama list`
- **Solution:** Try a different model or update Ollama

**Issue: Model is too slow**
- **Solution:** Use a smaller model (e.g., `deepseek-r1:7b` instead of `deepseek-r1:32b`)
- **Solution:** Adjust `num_predict` in `src/question_generator.py`

## Performance Considerations

### Model Size vs Speed
- **Small models (1-7B)**: Fast, good for development/testing
- **Medium models (7-14B)**: Balanced performance and quality
- **Large models (32B+)**: Best quality, slower

### Thinking Models
- Generate more tokens (thinking + answer)
- Take longer but produce better reasoning
- Recommended for production quality

### Standard Models
- Faster response times
- Direct JSON output
- Good for rapid development

## Best Practices

1. **Development**: Use smaller, faster models
   ```python
   ollama_model: str = "llama3.2:3b"
   ```

2. **Production**: Use larger, thinking models
   ```python
   ollama_model: str = "deepseek-r1:14b"
   ```

3. **Testing**: The system works with ANY model, so test freely!

4. **Monitoring**: Check logs to see which strategy succeeded:
   ```
   ✓ Success with free-form! Generated 5 questions...
   ✓ Success with json-format! Generated 5 questions...
   ```

## Advanced Configuration

### Adjust token limits
Edit `src/question_generator.py`:
```python
options = {
    'temperature': 0.7,    # Creativity (0.0-1.0)
    'top_p': 0.9,          # Nucleus sampling
    'num_predict': 4000    # Max tokens (adjust for your model)
}
```

### Model-Specific Settings
Some models may benefit from different settings:
```python
# For thinking models
'temperature': 0.6,  # Lower for more consistent reasoning

# For creative tasks
'temperature': 0.8,  # Higher for more variety
```

## Supported Ollama Models

Visit https://ollama.com/library to browse all available models.

**The system works with ALL of them!** 🎉
