from openai import OpenAI
from dotenv import load_dotenv
from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
import speech_recognition as sr
import os
import json
from Neo4jClient import Neo4jClient
import time
import pyttsx3
from datetime import datetime, timedelta
from rasa_sdk import Action
from rasa_sdk.events import SlotSet, ReminderScheduled
import csv
import random

# Load environment variables
load_dotenv()
API_KEY = os.getenv('api_key')

# Initialize clients
client = OpenAI(api_key=API_KEY)
GRAPH = Neo4jClient(uri="bolt://localhost:7687", user="neo4j", password="12345678")

engine = pyttsx3.init()

# Set properties (optional)
engine.setProperty('rate', 150)    # Speed (words per minute)
engine.setProperty('volume', 0.9)  # Volume (0.0 to 1.0)


import logging

# Configure logging


# Function to log a conversation
def log_conversation(csv_filename, actor, response, aoiname, objectname):
    # Open the CSV file in append mode
    with open(csv_filename, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)

        # If the file is empty, write the header
        if file.tell() == 0:
            writer.writerow(['Timestamp', 'Actor', 'Response', 'AOI', 'Object'])  # CSV header

        # Get the current timestamp
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

        # Write the log entry (timestamp, user input, bot response)
        writer.writerow([timestamp, actor, response, aoiname, objectname])


class ActionGetActorID(Action):

    def name(self) -> Text:
        return "action_get_actor_id"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        user_input = tracker.latest_message['text']
        #parsed_data = json.loads(user_input)
        # Get the message
        actor_id = user_input
        print(actor_id)
        result = GRAPH.creating_an_agent(actor_id,datetime.now().strftime('%Y%m%d%H%M%S'))
        agent_id = result[0]['agentID']

        print(f"Actor ID: {actor_id}, Agent ID: {agent_id}")
        dispatcher.utter_message(text=f"Actor ID: {actor_id}, Agent ID: {agent_id}")

        logging.basicConfig(
            filename=f'logs/conversation_{actor_id}.log',  # Log file name
            level=logging.INFO,  # Log level
            format='%(asctime)s - %(levelname)s - %(message)s'  # Log format
        )

        return [SlotSet("actorID", actor_id), SlotSet("agentID", agent_id)]


class ActionProvidingResponse(Action):

    def name(self) -> Text:
        return "action_providing_response"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        # Retrieve required slots
        #actor_id = tracker.get_slot("actorID")

        #agent_id = tracker.get_slot("agentID")


        agent_id = GRAPH.get_agent_id()[0]['id']
        actor_id = GRAPH.get_user_id()[0]['id']
        print(actor_id)
        print(agent_id)

        # Safely parse user input as JSON
        user_input = tracker.latest_message['text']
        #parsed_data = json.loads(user_input)
        # Get the message
        #user_input = parsed_data["message"]

        print(user_input)

        # Log user input

        names = ['A1', 'A2', 'A3', 'B1',
                 'B2', 'B3', 'B4', 'B5',
                 'C1', 'C2', 'C3', 'C4',
                 'C5', 'C6', 'D1', 'D2',
                 'D3', 'D4', 'D5']

        # print(GRAPH.get_last_obj_id(actor_id)[0]['b.objectName'])

        if GRAPH.get_last_obj_id(actor_id):
            if GRAPH.get_last_obj_id(actor_id)[0]['b.objectName'] in names:

                if user_input == 'Repeat Question':
                    responses = [
                        "Could you please repeat your question so I can assist you better?",
                        "I'm not entirely sure I understand; could you repeat your question?",
                        "Could you repeat your question? I might have missed something.",
                        "I want to make sure I got that right; could you repeat or confirm what you said?"
                    ]

                    self._log_conversation(actor_id, agent_id, user_input)
                    log_conversation('logs/conversation_' + str(actor_id) + '.csv', 'user_' + str(actor_id),
                                     user_input,
                                     GRAPH.get_last_aoi_id(actor_id)[0]['b.name'],
                                     GRAPH.get_last_obj_id(actor_id)[0]['b.objectName'])

                    # Select a random response
                    random_response = random.choice(responses)

                    engine.say(random_response)
                    engine.runAndWait()

                    self._log_conversation(agent_id, actor_id, random_response)

                    log_conversation('logs/conversation_' + str(actor_id) + '.csv', 'agent_' + str(agent_id),
                                     random_response,
                                     GRAPH.get_last_aoi_id(actor_id)[0]['b.name'],
                                     GRAPH.get_last_obj_id(actor_id)[0]['b.objectName'])


                else:
                    self._log_conversation(actor_id, agent_id, user_input)
                    log_conversation('logs/conversation_'+str(actor_id)+'.csv','user_'+str(actor_id), user_input, GRAPH.get_last_aoi_id(actor_id)[0]['b.name'], GRAPH.get_last_obj_id(actor_id)[0]['b.objectName'])

                    # Generate the system role for ChatGPT
                    system_role = self._get_system_role(actor_id, agent_id, user_input)


                    # Get response from ChatGPT
                    response = self.get_chatgpt_response(system_role, user_input)

                    print(response)
                    dispatcher.utter_message(response)
                    engine.say(response)
                    engine.runAndWait()

                    self._log_conversation(agent_id, actor_id, response)

                    log_conversation('logs/conversation_'+str(actor_id)+'.csv','agent_' + str(agent_id), response, GRAPH.get_last_aoi_id(actor_id)[0]['b.name'], GRAPH.get_last_obj_id(actor_id)[0]['b.objectName'])

                return [SlotSet("actorID", actor_id), SlotSet("agentID", agent_id)]
        else:
            if user_input == 'Repeat Question':
                responses = [
                    "Could you please repeat your question so I can assist you better?",
                    "I'm not entirely sure I understand; could you repeat your question?",
                    "Could you repeat your question? I might have missed something.",
                    "I want to make sure I got that right; could you repeat or confirm what you said?"
                ]

                self._log_conversation(actor_id, agent_id, user_input)
                log_conversation('logs/conversation_' + str(actor_id) + '.csv', 'user_' + str(actor_id), user_input,
                                 'None',
                                 'None')

                # Select a random response
                random_response = random.choice(responses)

                engine.say(random_response)
                engine.runAndWait()

                self._log_conversation(agent_id, actor_id, random_response)

                log_conversation('logs/conversation_' + str(actor_id) + '.csv', 'agent_' + str(agent_id),
                                 random_response,
                                 'None',
                                 'None')
            else:

                self._log_conversation(actor_id, agent_id, user_input)
                log_conversation('logs/conversation_' + str(actor_id) + '.csv', 'user_' + str(actor_id), user_input,
                                 'None',
                                 'None')

                system_role = f"""
                ### System Role
    
                You are an AI assistant serving as a virtual guide for a VR exhibition featuring five unique paintings. Your role is to provide insightful, engaging, and context-aware responses to enhance the user's exploration of the artworks.
    
                The user is not currently viewing any paintings. Guide them toward the five paintings in the main room of the exhibition and suggest they begin exploring one.
    
                ### Guidelines:
                - Invite the user to go to the main room and start looking at the paintings.
                - Do not include links, URLs, emojis, or unrelated content.
                - Avoid speculating or inventing details beyond the provided data.
                - Limit your response to no more than two sentences.
    
                ### Information Sources:
    
                - **Exhibit Data**: {GRAPH.get_graph_data()} – Includes general information about the exhibition, paintings, artists, historical context, and artistic styles.
    
                If exhibit- or painting-specific data is unavailable, inform the user that you do not have enough information and ask for their reflections.
                """

                response = self.get_chatgpt_response(system_role, user_input)

                print(response)
                dispatcher.utter_message(response)
                engine.say(response)
                engine.runAndWait()

                self._log_conversation(agent_id, actor_id, response)

                log_conversation('logs/conversation_' + str(actor_id) + '.csv', 'agent_' + str(agent_id), response,
                                 'None',
                                 'None')

            return [SlotSet("actorID", actor_id), SlotSet("agentID", agent_id)]


    def _get_system_role(self, actorID, agentID, user_input) -> str:
        return f"""
            ### System Role

            You are an AI assistant serving as a virtual museum guide for a VR exhibition of five unique paintings. 
            Your primary role is to provide insightful, engaging, and context-aware responses to user inquiries, enhancing their exploration of the artworks. 

            The exhibition environment is as follows:
                - The main room contains five paintings displayed across two walls.
                - On one wall, three paintings are arranged side by side in the following order (left to right):
                  1. Portrait of Pedro Sunda 
                  2. Portrait of Dom Miguel de Castro
                  3. Portrait of Diego Bemba
                - On the wall opposite, there are two paintings displayed in this order (left to right): 
                  1. Head of a Boy in a Turban
                  2. The African King Caspar
            
            Currently, the user is viewing a painting with the following details: ({GRAPH.get_last_obj(actorID)}).
            The specific area of the painting the user is focused on is: {GRAPH.get_last_aoi(actorID)}.
            Use the painting's image ({GRAPH.get_image_of_painting(actorID)}) to describe its visual aspects.

            Incorporate your prior response ({GRAPH.get_last_agent_response(actorID, agentID)}) to maintain continuity, as the user may be continuing the conversation. 
            Use the conversation history ({GRAPH.conversation_history(actorID, agentID)}) to avoid repetition and gauge the user's engagement level. Adjust your depth of explanation accordingly: 
            - For highly engaged users, provide detailed insights. 
            - For less engaged users, keep responses concise and to the point.
            
            **User Input**: {user_input}

            If the user's input is vague, ask clarifying questions such as: 
            “Would you like to know more about the colors used, the artist’s background, the themes of the painting, or its emotional impact?”

            If you have provided all the available information about the painting, thank the user and suggest exploring other artworks in the exhibition, offering to guide them if they are interested.
            
            ### Prioritization:
            - First, reference your previous response to maintain context and engagement.
            - Then, prioritize the user's current input or prompt to ensure their most recent inquiry is addressed.
            - Next, provide information about the specific area of the painting the user is observing.
            - If all available details about this area have already been shared, invite the user to explore other parts of the painting by highlighting interesting details in those areas, and discuss the painting as a whole.
            - If the observed area is the background, prioritize explaining the techniques used to create it.
            - Once all relevant details about the current painting have been shared, guide the conversation toward exploring other topics or artworks.
            
            ### Guidelines:
            - Do not include links, URLs, emojis, or unrelated content.
            - Avoid speculating or inventing details beyond the provided data.
            - Refrain from unnecessarily repeating the painting's name.
            - Avoid unnecessary repetition of information.
            - Limit your response to no more than two sentences.

            ### Information Sources:
            - **Exhibit Data**: {GRAPH.get_graph_data()} – Includes general information about the exhibition, paintings, artists, historical context, and artistic styles.

            If exhibit- or painting-specific data is unavailable, inform the user that you do not have enough information and ask them for their reflections.
        """

    def _log_conversation(self, first_actor, second_actor, response):
        """Logs the conversation with timestamps."""
        try:
            start_time = datetime.now().strftime('%Y%m%d%H%M%S')
            # Log conversation (adjustments to ensure time calculation happens after significant delay, if any)
            # duration = time.time() - start_time
            cleaned_text = response.replace("'", "").replace('"', "")
            GRAPH.import_conv(first_actor, second_actor, cleaned_text, start_time)
        except Exception as e:
            print(f"Error logging conversation: {str(e)}")

    def get_chatgpt_response(self, system_role, user_text=None):
        """Fetch a response from GPT."""
        try:
            messages = [{"role": "system", "content": system_role}]
            if user_text:
                messages.append({"role": "user", "content": user_text})

            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
            )
            return completion.choices[0].message.content

        except Exception as e:
            print(f"Error generating response: {str(e)}")
            return "An error occurred while generating the response."


class interactive_guide_interaction(Action):

    def name(self) -> Text:
        return "action_interactive_guide_interaction"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:



        agent_id = GRAPH.get_agent_id()[0]['id']
        actor_id = GRAPH.get_user_id()[0]['id']
        print(actor_id)

        names = ['A1', 'A2', 'A3', 'B1',
                 'B2', 'B3', 'B4', 'B5',
                 'C1', 'C2', 'C3', 'C4',
                 'C5', 'C6', 'D1', 'D2',
                 'D3', 'D4', 'D5']

        #print(GRAPH.get_last_obj_id(actor_id)[0]['b.objectName'])

        if GRAPH.get_last_obj_id(actor_id):
            if GRAPH.get_last_obj_id(actor_id)[0]['b.objectName'] in names:

                if GRAPH.get_last_time_of_interaction(actor_id, agent_id):
                    diff = float(datetime.now().strftime('%Y%m%d%H%M%S')) - float(GRAPH.get_last_time_of_interaction(actor_id, agent_id)[0]['tim'])
                else:
                    diff = float(datetime.now().strftime('%Y%m%d%H%M%S')) - 0

                print(diff)
                if diff > 30:
                    system_role = self.interactive_agent_prompt_with_gaze(actor_id,agent_id)

                    response = self.get_chatgpt_response(system_role)

                    self._log_conversation(agent_id, actor_id, response)
                    log_conversation('logs/conversation_'+str(actor_id)+'.csv','agent_' + str(agent_id), response, GRAPH.get_last_aoi_id(actor_id)[0]['b.name'], GRAPH.get_last_obj_id(actor_id)[0]['b.objectName'])

                    dispatcher.utter_message(response)
                    print(response)
                    engine.say(response)
                    engine.runAndWait()


        return [SlotSet("actorID", actor_id), SlotSet("agentID", agent_id)]

    def interactive_agent_prompt_with_gaze(self, actorID, agentID):
        return f"""
        ### System Role

        You are an AI assistant serving as a virtual museum guide in a VR exhibition featuring five unique paintings. 
        Your task is to engage users by encouraging interaction with the artworks and providing insightful information to enhance their experience.

        The exhibition environment is as follows:
            - The main room contains five paintings displayed across two walls.
            - On one wall, three paintings are arranged side by side in the following order (left to right):
              1. Portrait of Pedro Sunda 
              2. Portrait of Dom Miguel de Castro
              3. Portrait of Diego Bemba
            - On the wall opposite, there are two paintings displayed in this order (left to right): 
              1. Head of a Boy in a Turban
              2. The African King Caspar
        
        The user is currently observing a painting with the following details: ({GRAPH.get_last_obj(actorID)}).
        They are specifically focused on this area of the painting: {GRAPH.get_last_aoi(actorID)}.
        Use the painting's image ({GRAPH.get_image_of_painting(actorID)}) to describe its visual features.

        Use the conversation history ({GRAPH.conversation_history(actorID, agentID)}) to avoid repetition and gauge the user's engagement level. Adjust your depth of explanation accordingly: 
        - For highly engaged users, provide detailed insights. 
        - For less engaged users, keep responses concise and to the point.

        If you have provided all the available information about the painting, thank the user and suggest exploring other artworks in the exhibition, offering to guide them if they are interested.
        
        ### Prioritization:
        - Start by providing information about the specific area of the painting the user is observing.
        - If all available details about this area have already been shared, invite the user to explore other parts of the painting by highlighting interesting details in those areas, and discuss the painting as a whole.
        - If the observed area is the background, prioritize explaining the techniques used to create it.
        - Once all relevant details about the current painting have been shared, guide the conversation toward exploring other topics or artworks.

        ### Guidelines:
        - Do not include links, URLs, emojis, or unrelated content.
        - Avoid speculating or inventing details beyond the provided data.
        - Refrain from unnecessarily repeating the painting's name.
        - Avoid unnecessary repetition of information.
        - Limit your response to no more than two sentences.

    """


    def get_chatgpt_response(self, system_role, user_text=None):
            """Fetch a response from GPT."""
            try:
                messages = [{"role": "system", "content": system_role}]
                if user_text:
                    messages.append({"role": "user", "content": user_text})

                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                )
                return completion.choices[0].message.content

            except Exception as e:
                print(f"Error generating response: {str(e)}")
                return "An error occurred while generating the response."

    def _log_conversation(self, first_actor, second_actor, response):
        """Logs the conversation with timestamps."""
        try:
            start_time = datetime.now().strftime('%Y%m%d%H%M%S')
            # Log conversation (adjustments to ensure time calculation happens after significant delay, if any)
            # duration = time.time() - start_time
            cleaned_text = response.replace("'", "").replace('"', "")
            GRAPH.import_conv(first_actor, second_actor, cleaned_text, start_time)
        except Exception as e:
            print(f"Error logging conversation: {str(e)}")










