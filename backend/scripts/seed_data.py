import sys
import os

# Add parent dir to path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import SessionLocal, engine, Base
from app import models
from datetime import datetime

def init_db():
    Base.metadata.create_all(bind=engine)

def seed_data():
    db = SessionLocal()
    
    # Check if customer exists
    customer = db.query(models.Customer).filter(models.Customer.name == "张总").first()
    if not customer:
        print("Creating seed customer...")
        customer = models.Customer(
            name="张总",
            contact_info="13800138000",
            stage="trust_building",
            risk_profile="稳健型，对回撤敏感，偏好固收+。",
            summary="张总是某贸易公司老板，资金实力强，但投资风格保守。之前的投资在股票上亏损过，所以现在非常谨慎。目前主要沟通点在于建立信任，让他了解我们的风控体系。",
            created_at=datetime.utcnow()
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)
        
        # Add some chat history
        chats = [
            {"role": "user", "content": "张总，最近市场波动比较大，您之前的那个固收产品到期了吧？"},
            {"role": "ai", "content": "是的，刚好昨天到期。我现在有点犹豫，不知道该不该继续投。最近看新闻说股市好像不太好。"},
            {"role": "user", "content": "理解您的担心。确实最近大盘在调整。不过我们这次新发的产品主要是针对低风险偏好的客户，主打债券配置，回撤控制得很严。"},
            {"role": "ai", "content": "你们那个回撤控制，具体是怎么做的？上次那个理财经理也说控制得好，结果还是跌了 5%。"},
        ]
        
        for chat in chats:
            entry = models.CustomerData(
                customer_id=customer.id,
                source_type="chat_history_user" if chat["role"] == "ai" else "chat_history_ai", # Note: In DB user is AI agent user (sales), ai is customer... wait. 
                # Let's align with schema: 
                # source_type='chat_history_user' means message FROM USER (Sales)
                # source_type='chat_history_ai' means message FROM AI (Agent)? No.
                # Usually: 'user' = Sales, 'ai' = Agent. 
                # But here we are simulating Sales <-> Customer chat history.
                # The Agent is helping the Sales.
                # So the "Chat History" stored is Sales vs Customer.
                # Let's assume:
                # source_type='chat_history_user' -> Sales (User of the system)
                # But wait, in the dashboard:
                # msg.role === 'user' ? 'justify-end' : 'justify-start'
                # msg.role === 'user' (Sales) -> Right side (Blue)
                # msg.role === 'ai' (Customer?) -> Left side (White)
                # Wait, usually AI Agent chat is Sales vs AI.
                # BUT "Customer Detail" chat history is Sales vs Customer.
                # Let's clarify:
                # The dashboard shows "Chat History" which is the CONTEXT for the AI.
                # It is the record of communication between Sales and Customer.
                # In the code:
                # entry.source_type === 'chat_history_user' -> role: 'user'
                # entry.source_type === 'chat_history_ai' -> role: 'ai'
                # If this is Sales vs Customer:
                # User = Sales.
                # AI = ? (Customer?)
                # This naming is confusing in the current codebase.
                # Let's look at Dashboard.tsx:
                # history.push({ role: 'user', content: entry.content... })
                # history.push({ role: 'ai', content: entry.content... })
                # If this is the "Chat with AI Agent" regarding this customer, then it makes sense.
                # User asks AI: "How do I reply?"
                # AI answers: "You should say..."
                # BUT the user requirement says: "Input: Wechat history, Call recording...".
                # And "Entry Button 2: How should I reply?".
                # So the main chat window in "Work Area" is likely the interaction with the AI Agent.
                # AND the context (history) is displayed elsewhere or used implicitly?
                # Let's look at Dashboard.tsx again.
                # It loads `data_entries` into `chatHistory`.
                # And `handleSendMessage` sends to `customerApi.chat`.
                # So the main chat view IS the chat with the Agent.
                # The "Customer Context" (Sales vs Customer history) is likely part of the "Data Entries" list or used in the background.
                # Wait, `data_entries` contains `chat_history_user` and `chat_history_ai`.
                # If I upload a file, it becomes an entry.
                # If I chat with Agent, does it save to DB?
                # `customerApi.chat` -> `chat_service.chat_with_customer`.
                # Let's verify `chat_service.py`.
                content=chat["content"]
            )
            # Actually, let's just create some context entries (files/notes) and a few chat logs with the AGENT.
            # But for the "Simulation", maybe the user wants to see "Imported Chat History".
            # Let's assume the chat history in the dashboard IS the interaction with the AGENT.
            # So I will add some interaction logs.
            
            entry = models.CustomerData(
                customer_id=customer.id,
                source_type="chat_history_user" if chat["role"] == "user" else "chat_history_ai",
                content=chat["content"],
                created_at=datetime.utcnow()
            )
            db.add(entry)
        
        db.commit()
        print("Seed data created successfully.")
    else:
        print("Seed customer already exists.")

    db.close()

if __name__ == "__main__":
    init_db()
    seed_data()
