# MAST: Multi-Agent Software Team

## Overview

MAST (Multi-Agent Software Team) is a Python-based simulation of an autonomous software development team.  
It uses asynchronous agents to collaboratively design, implement, and test software projects.

### Agents

- Architect
- Product Owner
- UX Designer
- UI Designer
- Frontend Developer
- Backend Developer
- QA
- Security
- DevOps

Agents communicate via an event bus, share knowledge, and iteratively optimize outputs.  
After each sprint, benchmarks are created, technical challenges are logged, and agent behaviors are adjusted.

---

## Features

- **Autonomous Collaboration:** Agents interact based on the results of other agents.  
- **Sprint Cycles:** Each sprint has a goal, maximum duration of 2 minutes, and ends early if all agents complete.  
- **Benchmarking:** Performance metrics are generated after each sprint.  
- **Self-Improvement:** Agents adjust behavior based on benchmark results.  
- **File Generation:** All code, tests, and deployment artifacts are generated in the `./project` folder.  
- **LLM Integration:** Choose between **Ollama**, **OpenAI**, or **Anthropic Claude**.  
- **Recursive Prompting:** LLM responses are analyzed; extracted code segments are stored, other instructions are re-sent as prompts.  
- **Runtime Test Feedback:** Tests are automatically executed; failures are sent back to agents to improve the code.  
- **Clean Code Architecture:** Domain-specific paths, meaningful filenames, and auto-loaded classes/modules.  
- **Logging:** All interactions and results are recorded; dialog logs and performance charts are generated after each sprint.

---

## Requirements

- Python 3.10+
- asyncio
- pathlib
- dataclasses
- python-dotenv
- openai (if using OpenAI backend)
- anthropic (if using Claude backend)
- Ollama installed locally (for Ollama backend)

---

## Setup

1. Clone the repository.  
2. Install required Python packages:

```bash
pip install python-dotenv openai anthropic
```

3. Create a `.env` file with API keys (if using OpenAI or Claude):

```
OPENAI_API_KEY=your_openai_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

---

## Usage

```bash
python mast_agents.py
```

1. Choose the LLM backend (Ollama, OpenAI, or Claude).  
2. Select the model for the chosen backend.  
3. Enter the sprint goal.  
4. Agents will generate the project, run tests, automatically improve code, and save logs, benchmarks, and charts.

Example:

```
Select LLM backend:
1. Ollama
2. OpenAI
3. Claude
Enter number (default 1): 2
Enter OpenAI model (default gpt-4): gpt-4
Enter sprint goal: Create a Tic Tac Toe clone
```

---

## Project Structure

```
./project
    ├── src/
    │   ├── frontend/
    │   └── backend/
    ├── tests/
    ├── deploy/
    └── SECURITY.md
```

- Follows clean code principles: meaningful names, domain-specific structure, auto-loading of classes/modules.

---

## Logging & Metrics

- All agent communications are logged.  
- After each sprint, performance metrics are visualized in charts.  
- Dialog logs are saved in `project/dialog.txt`.  
- Test failures are automatically sent back to agents for code improvement.

---

## License

MIT License

