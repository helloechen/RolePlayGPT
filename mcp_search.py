"""
MCP (Model Context Protocol) 搜索增强模块
智能判断并执行网络搜索，为角色对话提供真实背景资料
"""
import re
import json
from typing import List, Dict, Optional
try:
    from ddgs import DDGS  # 新版本的包名
except ImportError:
    try:
        from duckduckgo_search import DDGS  # 向后兼容旧版本
    except ImportError:
        raise ImportError("请安装搜索包: pip install ddgs")
import requests
from bs4 import BeautifulSoup
from openai import OpenAI


class MCPSearchEngine:
    """MCP搜索引擎 - 智能判断并执行网络搜索"""
    
    def __init__(self, client: OpenAI):
        self.client = client
        self.ddgs = DDGS()
        
    def should_search(self, user_message: str, character_name: str) -> Dict:
        """
        使用GPT判断是否需要进行网络搜索
        
        参数:
            user_message: 用户的问题
            character_name: 当前角色名称
            
        返回:
            {
                "need_search": bool,
                "search_query": str,
                "reason": str
            }
        """
        decision_prompt = f"""你是一个智能搜索策略助手，负责判断用户的问题是否需要网络搜索，并生成最优搜索词。

角色：{character_name}
用户问题：{user_message}

**需要搜索的情况：**
1. 涉及具体的历史事件、故事情节细节
2. 提到原著中的具体场景、对话、台词
3. 询问角色背景故事的详细内容（如称号由来、经历、关系等）
4. 需要引用原作内容的问题
5. 询问具体的技术细节、专业知识
6. 需要真实数据、事实核查的问题

**搜索词生成原则：**
1. 使用精确的关键词组合（2-4个词）
2. 优先使用中文，包含核心概念
3. 避免太宽泛（如只搜"孙悟空"），要具体（如"孙悟空 齐天大圣 称号由来"）
4. 如果是角色相关，加上作品名（如"西游记 孙悟空 大闹天宫"）
5. 如果是技术问题，加上关键术语

请以JSON格式回复：
{{
    "need_search": true/false,
    "search_query": "精确的搜索关键词组合",
    "reason": "判断理由（为什么需要/不需要搜索）"
}}"""
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",  # 使用更便宜的模型做判断
                messages=[{"role": "user", "content": decision_prompt}],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            return result
            
        except Exception as e:
            print(f"MCP决策失败: {e}")
            return {"need_search": False, "search_query": "", "reason": "决策失败"}
    
    def fetch_webpage_content(self, url: str, max_length: int = 3000) -> str:
        """
        抓取网页全文内容
        
        参数:
            url: 网页URL
            max_length: 最大字符长度
            
        返回:
            网页文本内容
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=5)
            response.encoding = response.apparent_encoding
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 移除script和style标签
            for script in soup(['script', 'style', 'nav', 'footer', 'header']):
                script.decompose()
            
            # 提取文本
            text = soup.get_text(separator='\n', strip=True)
            
            # 清理多余空行
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            text = '\n'.join(lines)
            
            # 限制长度
            if len(text) > max_length:
                text = text[:max_length] + "..."
                
            return text
            
        except Exception as e:
            print(f"  ⚠️ 无法抓取网页 {url}: {e}")
            return ""
    
    def search_web(self, query: str, max_results: int = 8) -> List[Dict]:
        """
        使用DuckDuckGo搜索网络内容并抓取网页全文
        
        参数:
            query: 搜索关键词
            max_results: 最大结果数（增加到8）
            
        返回:
            搜索结果列表
        """
        try:
            results = []
            print(f"🔍 开始搜索: {query}")
            
            # 尝试多种搜索策略
            search_strategies = [
                {'region': None, 'safesearch': 'moderate'},  # 先不指定region
                {'region': 'wt-wt', 'safesearch': 'moderate'},  # 全球
                {'region': 'cn-zh', 'safesearch': 'off'},  # 中国区，关闭安全搜索
            ]
            
            for i, strategy in enumerate(search_strategies):
                try:
                    print(f"  策略 {i+1}: region={strategy['region']}, safesearch={strategy['safesearch']}")
                    
                    search_params = {
                        'query': query,  # 改为 'query' 而不是 'keywords'
                        'max_results': max_results,
                        'safesearch': strategy['safesearch']
                    }
                    if strategy['region']:
                        search_params['region'] = strategy['region']
                    
                    # 注意：新版ddgs包的API可能有变化
                    search_results = self.ddgs.text(**search_params)
                    
                    # 将生成器转换为列表
                    search_results_list = list(search_results) if search_results else []
                    
                    if search_results_list:
                        for r in search_results_list:
                            url = r.get('href', '')
                            title = r.get('title', '')
                            snippet = r.get('body', '')
                            
                            # 尝试抓取网页全文
                            print(f"  📄 抓取网页: {title[:50]}...")
                            full_content = self.fetch_webpage_content(url)
                            
                            results.append({
                                'title': title,
                                'snippet': snippet,
                                'full_content': full_content if full_content else snippet,
                                'url': url
                            })
                        print(f"  ✅ 成功！找到 {len(results)} 条结果，已抓取网页全文")
                        break  # 成功就退出
                    else:
                        print(f"  ❌ 策略 {i+1} 返回空结果，尝试下一个策略")
                        
                except Exception as strategy_error:
                    print(f"  ❌ 策略 {i+1} 失败: {strategy_error}")
                    continue
            
            if not results:
                print("⚠️ 所有搜索策略都未能找到结果")
            
            return results
            
        except Exception as e:
            print(f"❌ 搜索失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def summarize_search_results(self, query: str, results: List[Dict]) -> str:
        """
        使用GPT总结搜索结果（使用网页全文）
        
        参数:
            query: 搜索关键词
            results: 搜索结果列表
            
        返回:
            总结文本
        """
        if not results:
            return "未找到相关信息"
        
        # 构建搜索结果文本 - 使用全文内容，增加到前5个结果
        results_text = "\n\n" + "="*50 + "\n\n".join([
            f"【来源 {i+1}】{r['title']}\n网址：{r['url']}\n\n内容摘要：\n{r['full_content'][:1500]}"  # 使用全文，每个源最多1500字
            for i, r in enumerate(results[:5])  # 增加到5个结果
        ])
        
        summary_prompt = f"""你是一个专业的信息提取助手。请仔细阅读以下关于"{query}"的网页内容，提取最有价值的信息。

{results_text}

要求：
1. **深度提取**：从网页全文中提取详细的事实信息，包括背景、细节、数据等
2. **结构化输出**：用清晰的段落组织信息，包含：
   - 核心事实（是什么）
   - 背景信息（为什么、怎么来的）
   - 相关细节（具体情况、数据、例子）
3. **保持准确**：只使用搜索结果中的信息，不添加推测
4. **信息丰富**：输出应该是详细的（200-400字），而不是简单概括
5. **去重合并**：如果多个来源有相同信息，合并后只说一次
6. **保持中文**：全部使用中文输出

请提供详细的总结："""
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": summary_prompt}],
                temperature=0.3,
                max_tokens=1000  # 增加token限制，允许更详细的总结
            )
            
            summary = response.choices[0].message.content
            print(f"  📝 总结完成 ({len(summary)} 字)")
            return summary
            
        except Exception as e:
            print(f"总结失败: {e}")
            # 降级方案：返回前5个结果的全文摘要
            return "\n\n".join([
                f"【{r['title']}】\n{r['full_content'][:300]}"
                for r in results[:5]
            ])
    
    def enhance_context(self, 
                       user_message: str, 
                       character_name: str,
                       search_results_summary: str) -> str:
        """
        生成增强的上下文信息
        
        参数:
            user_message: 用户问题
            character_name: 角色名称
            search_results_summary: 搜索结果总结
            
        返回:
            增强的上下文文本
        """
        enhanced_context = f"""
【🔍 MCP背景知识增强】
用户询问：{user_message}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📚 相关真实资料（来自网络搜索并经AI提取）：

{search_results_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**重要指示：**
1. **优先使用真实资料**：以上搜索结果是从可靠来源提取的真实信息，请将其作为回答的主要依据
2. **融入角色人格**：用{character_name}的口吻、语言风格、性格特点来表达这些信息
3. **详细且生动**：基于这些详实的背景资料，给出丰富、具体、有细节的回答
4. **第一人称视角**：如果是角色自身的事情，用第一人称讲述（"我当时..."）
5. **自然引用**：将背景知识自然地融入对话中，就像角色在回忆或讲述自己的经历
6. **保持真实性**：不要编造搜索结果中没有的信息，如果某些细节不确定，可以说"我记得大概是..."

请现在以{character_name}的身份，基于上述真实资料，回答用户的问题。"""
        return enhanced_context


class MCPChatManager:
    """整合MCP搜索的对话管理器"""
    
    def __init__(self, openai_client: OpenAI):
        self.client = openai_client
        self.search_engine = MCPSearchEngine(openai_client)
        self.search_cache = {}  # 缓存搜索结果
    
    def chat_with_mcp(self, 
                      user_message: str,
                      character: Dict,
                      system_prompt: str,
                      conversation_history: List[Dict],
                      enable_search: bool = True,
                      model: str = "gpt-4o-ca",
                      temperature: float = 0.8,
                      max_tokens: int = 2000) -> Dict:
        """
        带MCP搜索增强的对话
        
        参数:
            user_message: 用户消息
            character: 角色信息字典
            system_prompt: 系统提示词
            conversation_history: 对话历史
            enable_search: 是否启用搜索
            model: 使用的模型
            temperature: 温度参数
            max_tokens: 最大token数
            
        返回:
            {
                "response": str,
                "tokens_used": int,
                "cost": float,
                "search_performed": bool,
                "search_query": str,
                "search_summary": str,
                "search_results": List[Dict]
            }
        """
        result = {
            "response": "",
            "tokens_used": 0,
            "cost": 0.0,
            "search_performed": False,
            "search_query": "",
            "search_summary": "",
            "search_results": []
        }
        
        # 1. MCP决策：是否需要搜索
        if enable_search:
            decision = self.search_engine.should_search(
                user_message, 
                character['name']
            )
            
            if decision['need_search']:
                search_query = decision['search_query']
                print(f"🔍 MCP触发搜索: {search_query}")
                
                # 检查缓存
                if search_query in self.search_cache:
                    search_summary = self.search_cache[search_query]['summary']
                    search_results = self.search_cache[search_query]['results']
                    print("📦 使用缓存的搜索结果")
                else:
                    # 2. 执行搜索（增加搜索结果数量）
                    search_results = self.search_engine.search_web(search_query, max_results=8)
                    
                    if search_results:
                        # 3. 总结搜索结果
                        search_summary = self.search_engine.summarize_search_results(
                            search_query, 
                            search_results
                        )
                        
                        # 缓存结果
                        self.search_cache[search_query] = {
                            'summary': search_summary,
                            'results': search_results
                        }
                        print(f"✅ 搜索完成，找到 {len(search_results)} 条结果")
                    else:
                        search_summary = "未找到相关信息"
                        search_results = []
                        print("❌ 搜索无结果")
                
                # 4. 增强系统提示词
                enhanced_context = self.search_engine.enhance_context(
                    user_message,
                    character['name'],
                    search_summary
                )
                
                system_prompt = f"{system_prompt}\n\n{enhanced_context}"
                
                result['search_performed'] = True
                result['search_query'] = search_query
                result['search_summary'] = search_summary
                result['search_results'] = search_results
        
        # 5. 构建消息列表
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})
        
        # 6. 调用GPT生成回复
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            result['response'] = response.choices[0].message.content
            result['tokens_used'] = response.usage.total_tokens
            
            # 计算费用（gpt-4o-ca定价）
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            result['cost'] = (prompt_tokens * 0.000005 + 
                            completion_tokens * 0.000015)
            
        except Exception as e:
            print(f"GPT调用失败: {e}")
            result['response'] = f"抱歉，回复生成失败：{str(e)}"
        
        return result

