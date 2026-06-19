import asyncio 

from langchain_groq import ChatGroq
from langchain.messages import SystemMessage, ToolMessage

from langchain_mcp_adapters.client import MultiServerMCPClient

from dotenv import load_dotenv

load_dotenv()

class ResearchAssistantAgent:
    def __init__(self):
        self.llm = ChatGroq(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            temperature=0.2,
            max_tokens=1024
        )

        self.tools_list = []
        self.tools_by_name = {}
        self.llm_with_tools = None 
        self.mcp_client = None

    async def _initialize_mcp_tools_async(self):
        if self.llm_with_tools is not None:
            return

        mcp_server_url = "http://127.0.0.1:5412/sse"

        try:
            self.mcp_client = MultiServerMCPClient({
                "research_server": {
                    "transport": "sse",
                    "url": mcp_server_url
                }
            })
            self.tools_list = await self.mcp_client.get_tools()

            if not self.tools_list:
                raise ValueError("MCP Server connected, No tools returned")

            self.tools_by_name = {tool.name: tool for tool in self.tools_list}
            self.llm_with_tools = self.llm.bind_tools(self.tools_list) 

            print(f"Connected to MCP Server, fetched {len(self.tools_list)} tools.")        

        except Exception as e:
            raise RuntimeError(
                f"Could not initialise MCP Client at {mcp_server_url}\n"
                f"Reason: {e}"
            )

    async def call_llm(self, state):
        await self._initialize_mcp_tools_async()
        
        return {
            "messages": [
                await self.llm_with_tools.ainvoke(
                    [
                        SystemMessage(
                            content="""
                            You are an expert research Assistant.
                            Your task is to look for complex topics, reference from academic and online 
                            databases and generate high quality summaries that can help me start writing
                            my literature review.

                            Follow this process:

                            1. You have tools that can help with web searches. Use them to find kinks or extract 
                            detailed web content. refer to blogs, articles and documentation.

                            2. You ahve access to reserach repositories as well, use them to extarct
                            paper content and generate educated summaries.

                            3. Compare all the found content, create technical breakdown, compare introductions,
                            to provide the said output.

                            Rely ONLY on your provided tools for real world factual claims. 
                            """
                        )
                    ]
                    + state['messages']
                )
            ],
            "llm_calls": state.get('llm_calls', 0) + 1
        }

    async def tool_node(self, state):
        """Performs the tool calls"""
        await self._initialize_mcp_tools_async()

        result = []

        for tool_call in state['messages'][-1].tool_calls:

            if 'self' in tool_call["args"]:
                del tool_call["args"]['self']

            tool = self.tools_by_name[tool_call["name"]]
            observation = await tool.ainvoke(tool_call["args"])

            content_string = str(observation)

            MAX_CHARACTERS = 8000
            if len(content_string) > MAX_CHARACTERS:
                content_string = (
                    content_string[:MAX_CHARACTERS] +
                    "\n\n [..OUTPUT TRUNCATED TO FIT context limits.. ]"
                )

            result.append(
                ToolMessage(
                    content=content_string,
                    tool_call_id=tool_call["id"]
                )
            )

        return {"messages": result}