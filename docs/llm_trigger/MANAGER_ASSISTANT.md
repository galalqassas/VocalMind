# AI Manager Assistant (Text-to-SQL)

The AI Manager Assistant is a natural language interface that allows managers to query performance, metrics, and call details using natural language.

---

## 1. Text-to-SQL Architecture

The Assistant parses natural language inputs and translates them into SQL using LLMs. Below is the operational flow:

```mermaid
graph TD
    User[Manager User Query] --> Route[Gateway assistant/query route]
    Route --> Context[Fetch session conversation history]
    Context --> Provider{ASSISTANT_LLM_PROVIDER setting}
    
    Provider -- gemini --> Gemini[Google GenAI Client]
    Provider -- groq --> Groq[Groq Chat Client]
    Provider -- ollama --> Ollama[Local Ollama Client]
    
    Gemini --> SQL[Generate raw SQL query]
    Groq --> SQL
    Ollama --> SQL
    
    SQL --> Security{Read-Only Check & Sanitizer}
    Security -- Write keyword detected --> Error[Raise 400 Bad Request]
    Security -- Valid select --> Execute[Execute read-only SQL in Postgres]
    
    Execute --> Results[Retrieve query rows]
    Results --> Synthesis[LLM synthesizes response text]
    Synthesis --> Output[JSON Response to Frontend]
```

---

## 2. LLM Provider Fallbacks

Assistant generation is managed via GenAI endpoints:

1.  **Google GenAI (Gemini)**: The primary engine if `GOOGLE_API_KEY` is set. Candidates are tried in order: `gemini-2.0-flash`, `gemini-2.5-flash`, `gemini-1.5-flash`.
2.  **Groq (Llama-3)**: The secondary cloud provider if Gemini is disabled or credentials are missing.
3.  **Ollama (qwen2.5:7b)**: The local fallback engine. If cloud models fail or return rate-limit errors, the backend routes generation locally to Ollama, ensuring continuous service availability.

---

## 3. Security & Safety Controls

Because the Assistant translates text into executable database commands, the gateway enforces safety checks:

*   **Read-Only Strictness**: The Assistant parses the generated SQL using regular expressions and string checks. If it contains words like `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, or `CREATE`, the query is blocked.
*   **Database Transaction Isolation**: The SQL is executed in a read-only transaction context to prevent unauthorized writes.

---

## 4. Operational Features

*   **Ordinal References**: The Assistant preserves conversation state. If a manager asks *"Show me Priya's calls"* and follows up with *"Show me details for the second one"*, the assistant resolves "the second one" based on the previous query results.
*   **SQL Repair**: If the generated SQL returns a database syntax error, the assistant catches the error, appends it to a correction prompt, and queries the LLM again to repair the syntax.
