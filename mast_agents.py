import os
import json
import asyncio
import httpx
import re
from pathlib import Path
from dotenv import load_dotenv
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic

# ---------------------------------------------------------------------
# Load environment variables
# ---------------------------------------------------------------------
load_dotenv()
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
CLAUDE_KEY = os.getenv("ANTHROPIC_API_KEY")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# ---------------------------------------------------------------------
# Unified LLM call function
# ---------------------------------------------------------------------
async def call_llm(backend, client, model_name, prompt, timeout=60):
    try:
        if backend == "openai":
            resp = await client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                timeout=timeout
            )
            return resp.choices[0].message.content

        elif backend == "claude":
            resp = await client.messages.create(
                model=model_name,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}]
            )
            return resp.content[0].text

        elif backend == "ollama":
            async with httpx.AsyncClient() as http_client:
                r = await http_client.post(
                    f"{client}/api/generate",
                    json={"model": model_name, "prompt": prompt},
                    timeout=timeout
                )
                out = ""
                for line in r.text.splitlines():
                    try:
                        data = json.loads(line)
                        out += data.get("response", "")
                    except Exception:
                        continue
                return out
    except Exception as e:
        return f"LLM call failed: {str(e)}"

# ---------------------------------------------------------------------
# File Management Utilities
# ---------------------------------------------------------------------
def extract_code_blocks(text):
    """Extract code blocks with filenames from agent output"""
    code_blocks = []
    
    # Pattern for ```filename or ```language:filename
    pattern = r'```(?:(\w+):)?([^\n]+)\n(.*?)```'
    matches = re.findall(pattern, text, re.DOTALL)
    
    for language, filename, code in matches:
        if filename.strip() and not filename.startswith('bash') and not filename.startswith('shell'):
            code_blocks.append({
                'filename': filename.strip(),
                'language': language or 'txt',
                'content': code.strip()
            })
    
    # Also look for explicit file patterns
    file_pattern = r'(?:File|Filename|Path):\s*([^\n]+)\n(.*?)(?=\n(?:File|Filename|Path):|$)'
    file_matches = re.findall(file_pattern, text, re.DOTALL | re.IGNORECASE)
    
    for filename, content in file_matches:
        if filename.strip():
            code_blocks.append({
                'filename': filename.strip(),
                'language': 'txt',
                'content': content.strip()
            })
    
    return code_blocks

def create_files_from_blocks(code_blocks, base_path="project"):
    """Create actual files from extracted code blocks"""
    created_files = []
    base_dir = Path(base_path)
    base_dir.mkdir(exist_ok=True)
    
    for block in code_blocks:
        file_path = base_dir / block['filename']
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(block['content'])
            created_files.append(str(file_path))
            print(f"Created: {file_path}")
        except Exception as e:
            print(f"Failed to create {file_path}: {e}")
    
    return created_files

def analyze_project_files(base_path="project"):
    """Analyze existing project files"""
    base_dir = Path(base_path)
    if not base_dir.exists():
        return "No project files found."
    
    analysis = []
    for file_path in base_dir.rglob('*'):
        if file_path.is_file():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines = len(content.splitlines())
                    analysis.append(f"{file_path}: {lines} lines")
            except Exception:
                analysis.append(f"{file_path}: [binary/unreadable]")
    
    return "\n".join(analysis) if analysis else "No readable files found."

# ---------------------------------------------------------------------
# Inter-Agent Communication System
# ---------------------------------------------------------------------
class Message:
    def __init__(self, sender, recipient, content, message_type="feedback"):
        self.sender = sender
        self.recipient = recipient
        self.content = content
        self.message_type = message_type
        self.timestamp = asyncio.get_event_loop().time()

class CommunicationHub:
    def __init__(self):
        self.messages = []
        self.agent_registry = {}
    
    def register_agent(self, agent):
        self.agent_registry[agent.name] = agent
        agent.communication_hub = self
    
    def send_message(self, sender_name, recipient_name, content, message_type="feedback"):
        message = Message(sender_name, recipient_name, content, message_type)
        self.messages.append(message)
        print(f"💬 {sender_name} → {recipient_name}: {message_type}")
    
    def get_messages_for_agent(self, agent_name, message_type=None):
        messages = [m for m in self.messages if m.recipient == agent_name]
        if message_type:
            messages = [m for m in messages if m.message_type == message_type]
        return messages
    
    def get_recent_outputs(self):
        """Get recent outputs from all agents for cross-communication"""
        outputs = {}
        for name, agent in self.agent_registry.items():
            if hasattr(agent, 'result') and agent.result:
                outputs[name] = agent.result
        return outputs

# ---------------------------------------------------------------------
# Agent base class
# ---------------------------------------------------------------------
class Agent:
    def __init__(self, name, role, backend, client, model):
        self.name = name
        self.role = role
        self.backend = backend
        self.client = client
        self.model = model
        self.result = None
        self.created_files = []
        self.communication_hub = None
        self.collaboration_history = []

    async def run(self, prompt, context_from_others=None):
        print(f"\n{self.name} is working on: {self.role}")
        
        # Get messages from other agents
        messages = []
        if self.communication_hub:
            messages = self.communication_hub.get_messages_for_agent(self.name)
        
        # Enhance prompt with peer feedback and context
        enhanced_prompt = self._build_enhanced_prompt(prompt, context_from_others, messages)
        
        self.result = await call_llm(self.backend, self.client, self.model, enhanced_prompt)
        
        # Extract and create files from the result
        code_blocks = extract_code_blocks(self.result)
        if code_blocks:
            print(f"{self.name} creating {len(code_blocks)} files...")
            self.created_files = create_files_from_blocks(code_blocks)
        
        # Send feedback to other agents after completing work
        await self._provide_feedback_to_peers()
        
        print(f"{self.name} finished.\n")
        return self.result

    def _build_enhanced_prompt(self, base_prompt, context, messages):
        """Build enhanced prompt with peer input"""
        enhanced = base_prompt
        
        # Add context from other agents
        if context:
            enhanced += f"\n\n=== CONTEXT FROM OTHER TEAM MEMBERS ===\n{context}"
        
        # Add feedback from peers
        if messages:
            feedback_text = "\n".join([f"- {m.sender}: {m.content}" for m in messages])
            enhanced += f"\n\n=== FEEDBACK FROM TEAM ===\n{feedback_text}"
            enhanced += "\nPlease consider this feedback in your work."
        
        return enhanced

    async def _provide_feedback_to_peers(self):
        """Send feedback to other relevant agents"""
        if not self.communication_hub:
            return
        
        # Get insights about other agents' work
        feedback_targets = self._get_feedback_targets()
        
        for target_agent, feedback_type in feedback_targets.items():
            if target_agent != self.name:
                feedback = await self._generate_feedback_for_agent(target_agent, feedback_type)
                if feedback:
                    self.communication_hub.send_message(
                        self.name, target_agent, feedback, feedback_type
                    )

    def _get_feedback_targets(self):
        """Define which agents this agent should provide feedback to"""
        return {}  # Override in subclasses

    async def _generate_feedback_for_agent(self, target_agent, feedback_type):
        """Generate specific feedback for another agent"""
        if not self.result:
            return None
        
        prompt = f"""
        Based on my work as {self.name} ({self.role}), provide brief, actionable feedback 
        for the {target_agent} regarding {feedback_type}.
        
        My output: {self.result[:500]}...
        
        Provide 1-2 specific suggestions that would improve their work.
        Keep it concise and constructive.
        """
        
        try:
            feedback = await call_llm(self.backend, self.client, self.model, prompt)
            return feedback
        except:
            return None

    def send_message_to_agent(self, recipient, content, message_type="collaboration"):
        """Send direct message to another agent"""
        if self.communication_hub:
            self.communication_hub.send_message(self.name, recipient, content, message_type)

# ---------------------------------------------------------------------
# Specific Agents
# ---------------------------------------------------------------------
class ProductOwnerAgent(Agent):
    async def run(self, sprint_goal):
        prompt = f"""
        You are the Product Owner. Define clear development tasks for this sprint goal:
        '{sprint_goal}'.

        Each task must include:
        - Task name
        - Description
        - Complexity (1-5)
        """
        return await super().run(prompt)

class ArchitectAgent(Agent):
    async def run(self, sprint_goal):
        prompt = f"""
        You are the Software Architect. Based on the sprint goal '{sprint_goal}',
        define a clean architecture for the project:
        - Technologies to use
        - File and path structure
        """
        return await super().run(prompt)

class BackendAgent(Agent):
    async def run(self, arch_output):
        prompt = f"""
        You are the Backend Developer. Based on the following architecture plan:
        {arch_output}

        Write backend service code (Python preferred).
        Format your response with clear code blocks using:
        ```python:filename.py
        [code here]
        ```
        
        Create complete, runnable files with proper imports and structure.
        Consider API endpoints that the frontend will need.
        """
        return await super().run(prompt, arch_output)
    
    def _get_feedback_targets(self):
        return {
            "Frontend Dev": "API integration",
            "DevOps": "deployment requirements", 
            "Architect": "technical implementation"
        }

class FrontendAgent(Agent):
    async def run(self, ui_output):
        prompt = f"""
        You are the Frontend Developer. Based on these UI mockups or flows:
        {ui_output}

        Generate production-ready frontend code (HTML/CSS/JS or React).
        Format your response with clear code blocks using:
        ```html:index.html
        [code here]
        ```
        ```css:styles.css
        [code here]
        ```
        ```javascript:app.js
        [code here]
        ```
        
        Create complete, functional files that integrate with backend APIs.
        Consider responsive design and user experience.
        """
        return await super().run(prompt, ui_output)
    
    def _get_feedback_targets(self):
        return {
            "Backend Dev": "API requirements",
            "UI Designer": "visual implementation",
            "UX Designer": "user interaction flow"
        }

class UXDesignerAgent(Agent):
    async def run(self, sprint_goal):
        prompt = f"""
        You are the UX Designer. Based on sprint goal '{sprint_goal}',
        describe user flows in detail. Consider:
        - User personas and their needs
        - Task flows and user journeys
        - Pain points and solutions
        - Interaction patterns
        """
        return await super().run(prompt, sprint_goal)
    
    def _get_feedback_targets(self):
        return {
            "UI Designer": "visual design direction",
            "Frontend Dev": "interaction requirements",
            "Product Owner": "user requirements validation"
        }

class UIDesignerAgent(Agent):
    async def run(self, ux_output):
        prompt = f"""
        You are the UI Designer. Based on these UX flows:
        {ux_output}

        Provide detailed UI design mockups including:
        - Component specifications
        - Layout and spacing guidelines
        - Color schemes and typography
        - Interactive elements
        - Responsive behavior
        """
        return await super().run(prompt, ux_output)
    
    def _get_feedback_targets(self):
        return {
            "Frontend Dev": "implementation feasibility",
            "UX Designer": "design alignment with flows",
            "Product Owner": "business requirements alignment"
        }

class DevOpsAgent(Agent):
    async def run(self, arch_output):
        prompt = f"""
        You are the DevOps Engineer. Based on this architecture:
        {arch_output}

        Create deployment configuration including:
        - Dockerfile for containerization
        - Docker-compose for multi-service setup
        - Environment configuration
        - Health checks and monitoring
        - Scalability considerations
        
        Format your response with:
        ```dockerfile:Dockerfile
        [dockerfile content]
        ```
        ```yaml:docker-compose.yml
        [compose content]
        ```
        """
        return await super().run(prompt, arch_output)
    
    def _get_feedback_targets(self):
        return {
            "Backend Dev": "runtime requirements",
            "Architect": "infrastructure alignment"
        }

class AnalystAgent(Agent):
    async def run(self, project_files):
        prompt = f"""
        You are the Code Analyst. Analyze these existing project files:
        {project_files}

        Provide comprehensive analysis:
        1. Code quality assessment
        2. Architecture review  
        3. Security considerations
        4. Performance optimization opportunities
        5. Suggestions for next iteration
        6. Integration issues between components
        
        Be specific and actionable in your feedback.
        """
        return await super().run(prompt, project_files)
    
    def _get_feedback_targets(self):
        return {
            "Backend Dev": "code quality improvements",
            "Frontend Dev": "optimization suggestions", 
            "DevOps": "deployment improvements",
            "Architect": "architectural concerns"
        }

# ---------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------
class SprintCoordinator:
    def __init__(self, agents):
        self.agents = agents
        self.sprint_count = 0
        self.communication_hub = CommunicationHub()
        
        # Register all agents with the communication hub
        for agent in self.agents:
            self.communication_hub.register_agent(agent)

    async def run_sprint(self, goal):
        self.sprint_count += 1
        print(f"\nStarting Sprint #{self.sprint_count} with Enhanced Communication")
        print("Agents will collaborate and provide feedback to each other")
        
        # Analyze existing files before starting (if not first sprint)
        if self.sprint_count > 1:
            print("\nAnalyzing existing project files...")
            file_analysis = analyze_project_files()
            
            analyst = next((a for a in self.agents if isinstance(a, AnalystAgent)), None)
            if analyst:
                analysis_output = await analyst.run(file_analysis)
                print("\n--- File Analysis ---\n", analysis_output)
        
        # Phase 1: Planning and Design (with cross-collaboration)
        print("\n📋 Phase 1: Planning & Design")
        product_owner = next(a for a in self.agents if isinstance(a, ProductOwnerAgent))
        architect = next(a for a in self.agents if isinstance(a, ArchitectAgent))
        ux = next(a for a in self.agents if isinstance(a, UXDesignerAgent))
        
        po_out = await product_owner.run(goal)
        arch_out = await architect.run(goal)
        ux_out = await ux.run(goal)
        
        # Phase 2: UI Design (with feedback from UX and input from technical team)
        print("\nPhase 2: UI Design")
        ui = next(a for a in self.agents if isinstance(a, UIDesignerAgent))
        ui_out = await ui.run(ux_out)
        
        # Phase 3: Development (with cross-team collaboration)
        print("\n⚙Phase 3: Development & Deployment")
        backend = next(a for a in self.agents if isinstance(a, BackendAgent))
        frontend = next(a for a in self.agents if isinstance(a, FrontendAgent))
        devops = next(a for a in self.agents if isinstance(a, DevOpsAgent))
        
        # Run development tasks with enhanced collaboration
        backend_out = await backend.run(arch_out)
        frontend_out = await frontend.run(ui_out)
        devops_out = await devops.run(arch_out)
        
        # Phase 4: Collaboration Review Round
        print("\nPhase 4: Collaboration Review")
        await self._run_collaboration_round()

        print(f"\nSprint #{self.sprint_count} Results:")
        print("\n--- Product Owner Tasks ---\n", po_out)
        print("\n--- Architecture ---\n", arch_out)
        print("\n--- UX Flows ---\n", ux_out)
        print("\n--- UI Mockups ---\n", ui_out)
        print("\n--- Backend Code ---\n", backend_out)
        print("\n--- Frontend Code ---\n", frontend_out)
        print("\n--- DevOps (Dockerfile) ---\n", devops_out)
        
        # Summary of created files and communications
        all_files = []
        for agent in [backend, frontend, devops]:
            all_files.extend(agent.created_files)
        
        if all_files:
            print(f"\nFiles created in Sprint #{self.sprint_count}:")
            for file_path in all_files:
                print(f"  - {file_path}")
        
        # Show communication summary
        print(f"\nCommunication Summary:")
        print(f"  Total messages exchanged: {len(self.communication_hub.messages)}")
        
    async def _run_collaboration_round(self):
        """Run a round of cross-agent collaboration and improvements"""
        print("Agents reviewing each other's work...")
        
        # Get all current outputs for context
        recent_outputs = self.communication_hub.get_recent_outputs()
        
        # Create improvement prompts based on peer feedback
        improvement_tasks = []
        
        for agent in self.agents:
            if hasattr(agent, 'result') and agent.result:
                # Get feedback messages for this agent
                messages = self.communication_hub.get_messages_for_agent(agent.name)
                
                if messages:
                    print(f"🔧 {agent.name} incorporating feedback...")
                    # Could run improvement iterations here if needed
                    # This is where agents could refine their work based on peer input

    async def run_multiple_sprints(self, goals):
        """Run multiple sprint iterations"""
        for i, goal in enumerate(goals, 1):
            print(f"\n{'='*60}")
            print(f"SPRINT ITERATION {i}: {goal}")
            print('='*60)
            await self.run_sprint(goal)
            
            if i < len(goals):
                print(f"\nSprint #{i} completed. Files will be analyzed before next sprint...")
                input("Press Enter to continue to next sprint...")

# ---------------------------------------------------------------------
# Model Selection
# ---------------------------------------------------------------------
async def select_backend_and_model():
    print("\nSelect LLM backend:")
    print("1. OpenAI")
    print("2. Claude (Anthropic)")
    print("3. Ollama (local)")

    choice = input("Enter choice [1]: ") or "1"

    if choice == "1":
        client = AsyncOpenAI(api_key=OPENAI_KEY)
        model = input("Enter OpenAI model [gpt-4o-mini]: ") or "gpt-4o-mini"
        return "openai", client, model

    elif choice == "2":
        client = AsyncAnthropic(api_key=CLAUDE_KEY)
        model = input("Enter Claude model [claude-3-5-sonnet-20240620]: ") or "claude-3-5-sonnet-20240620"
        return "claude", client, model

    elif choice == "3":
        async with httpx.AsyncClient() as http_client:
            try:
                r = await http_client.get(f"{OLLAMA_HOST}/api/tags", timeout=10)
                models = [m["name"] for m in r.json().get("models", [])]
            except Exception:
                models = []
        print("Available Ollama models:", models or ["<none>"])
        model = input(f"Enter Ollama model [{models[0] if models else 'llama3'}]: ") or (models[0] if models else "llama3")
        return "ollama", OLLAMA_HOST, model

# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
async def main():
    backend, client, model = await select_backend_and_model()
    
    print("\nChoose mode:")
    print("1. Single Sprint")
    print("2. Multiple Sprint Iterations")
    
    mode = input("Enter choice [1]: ") or "1"
    
    agents = [
        ProductOwnerAgent("Product Owner", "Define tasks", backend, client, model),
        ArchitectAgent("Architect", "Define architecture", backend, client, model),
        UXDesignerAgent("UX Designer", "Design UX flows", backend, client, model),
        UIDesignerAgent("UI Designer", "Design UI mockups", backend, client, model),
        BackendAgent("Backend Dev", "Build backend", backend, client, model),
        FrontendAgent("Frontend Dev", "Build frontend", backend, client, model),
        DevOpsAgent("DevOps", "Write Dockerfile", backend, client, model),
        AnalystAgent("Analyst", "Analyze code", backend, client, model),
    ]

    coordinator = SprintCoordinator(agents)
    
    if mode == "1":
        goal = input("\nEnter Sprint Goal: ")
        await coordinator.run_sprint(goal)
    else:
        print("\nEnter sprint goals (empty line to finish):")
        goals = []
        while True:
            goal = input(f"Sprint {len(goals) + 1}: ").strip()
            if not goal:
                break
            goals.append(goal)
        
        if goals:
            await coordinator.run_multiple_sprints(goals)
        else:
            print("No goals entered.")

if __name__ == "__main__":
    asyncio.run(main())

