import base64
import time
import enum
from typing import List, Dict, Any, Optional, Union, Tuple
from openai import OpenAI

class AgentStatus(enum.Enum):
    """Status of an agent action."""
    COMPLETE = "complete"           # Action completed successfully
    NEEDS_INPUT = "needs_input"     # Agent needs more input from the user
    NEEDS_SAFETY_CHECK = "needs_safety_check"  # Safety check needs acknowledgment
    ERROR = "error"                # An error occurred

class Agent:
    """
    Agent class for integrating OpenAI's agent capabilities with a desktop environment.
    This class handles the agentic loop for controlling a desktop environment through
    natural language commands and visual feedback.
    
    The Agent maintains state internally, tracking conversation history, pending calls,
    and safety checks, making it easier to interact with the agent through a simple
    status-based API.
    """

    def __init__(self, desktop=None, openai_api_key=None):
        """
        Initialize an Agent instance.
        
        Args:
            desktop: A Desktop instance to control. Can be set later with set_desktop().
            openai_api_key: OpenAI API key for authentication. If None, will try to use
                           the one from the desktop or environment variables.
        """
        self.desktop = desktop
        
        # Set up OpenAI API key and client
        if openai_api_key is None and desktop is not None:
            openai_api_key = desktop.openai_api_key
            
        if openai_api_key is not None:
            self.openai_api_key = openai_api_key
            self.openai_client = OpenAI(api_key=openai_api_key)
        else:
            self.openai_api_key = None
            self.openai_client = None
            
        # Initialize state tracking
        self._response_history = []  # List of all responses from the API
        self._input_history = []     # List of all inputs sent to the API
        self._current_response = None  # Current response object
        self._pending_call = None     # Pending computer call that needs safety check acknowledgment
        self._pending_safety_checks = []  # Pending safety checks
        self._needs_input = []        # Messages requesting user input
        self._error = None            # Last error message, if any

    def set_desktop(self, desktop):
        """
        Set or update the desktop instance this agent controls.
        
        Args:
            desktop: A Desktop instance to control.
        """
        self.desktop = desktop
        
        # If we don't have an API key yet, try to get it from the desktop
        if self.openai_api_key is None and desktop.openai_api_key is not None:
            self.openai_api_key = desktop.openai_api_key
            self.openai_client = OpenAI(api_key=self.openai_api_key)

    def handle_model_action(self, action):
        """
        Given a computer action (e.g., click, double_click, scroll, etc.),
        execute the corresponding operation on the Desktop environment.
        
        Args:
            action: An action object from the OpenAI model response.
            
        Returns:
            Screenshot bytes if the action is a screenshot, None otherwise.
        """
        if self.desktop is None:
            raise ValueError("No desktop has been set for this agent.")
            
        action_type = action.type

        try:
            match action_type:
            
                case "click":
                    x, y = int(action.x), int(action.y)
                    self.desktop.click(x, y, action.button)

                case "scroll":
                    x, y = int(action.x), int(action.y)
                    scroll_x, scroll_y = int(action.scroll_x), int(action.scroll_y)
                    self.desktop.scroll(x, y, scroll_x=scroll_x, scroll_y=scroll_y)
                
                case "keypress":
                    keys = action.keys
                    self.desktop.keypress(keys)
                
                case "type":
                    text = action.text
                    self.desktop.type_text(text)
                
                case "wait":
                    time.sleep(2)

                case "screenshot":
                    # Nothing to do as screenshot is taken at each turn
                    screenshot_bytes = self.desktop.get_screenshot()
                    return screenshot_bytes
                
                # Handle other actions here

                case _:
                    print(f"Unrecognized action: {action}")

        except Exception as e:
            print(f"Error handling action {action}: {e}")

    def computer_use_loop(self, response):
        """
        Run the loop that executes computer actions until no 'computer_call' is found,
        handling pending safety checks BEFORE actually executing the call.
        
        Args:
            response: A response object from the OpenAI API.
            
        Returns:
            (response, messages, safety_checks, pending_call)
            - response: the latest (or final) response object
            - messages: a list of "message" items if user input is requested (or None)
            - safety_checks: a list of pending safety checks if any (or None)
            - pending_call: if there's exactly one computer_call that was paused
                due to safety checks, return that here so the caller can handle it
                after the user acknowledges the checks.
        """
        if self.desktop is None:
            raise ValueError("No desktop has been set for this agent.")
        
        # Identify all message items (the agent wants text input)
        messages = [item for item in response.output if item.type == "message"]

        # Identify any computer_call items
        computer_calls = [item for item in response.output if item.type == "computer_call"]

        # For simplicity, assume the agent only issues ONE call at a time
        computer_call = computer_calls[0] if computer_calls else None

        # Identify all safety checks across items
        all_safety_checks = []
        for item in response.output:
            checks = getattr(item, "pending_safety_checks", None)
            if checks:
                all_safety_checks.extend(checks)

        # If there's a computer_call that also has safety checks,
        # we must return immediately so the user can acknowledge them first.
        # We'll do so by returning the "pending_call" plus the checks.
        if computer_call and all_safety_checks:
            return response, messages or None, all_safety_checks, computer_call

        # If there's no computer_call at all, but we do have messages or checks
        # we return them so the caller can handle user input or safety checks.
        if not computer_call:
            if messages or all_safety_checks:
                print("* RESPONSE: ")
                print(response)
                print("\n---------\n")
                return response, messages or None, all_safety_checks or None, None
            # Otherwise, no calls, no messages, no checks => done
            print("No actionable computer_call or interactive prompt found. Finishing loop.")
            return response, None, None, None

        # If we got here, that means there's a computer_call *without* any safety checks,
        # so we can proceed to execute it right away.

        # Execute the call
        self.handle_model_action(computer_call.action)
        time.sleep(1)  # small delay to allow environment changes

        # Take a screenshot
        screenshot_base64 = self.desktop.get_screenshot()
        image_data = base64.b64decode(screenshot_base64)
        with open("output_image.png", "wb") as f:
            f.write(image_data)
        print("* Saved image data.")

        # Now send that screenshot back as `computer_call_output`
        new_response = self.openai_client.responses.create(
            model="computer-use-preview",
            previous_response_id=response.id,
            tools=[
                {
                    "type": "computer_use_preview",
                    "display_width": 1024,
                    "display_height": 768,
                    "environment": "linux"
                }
            ],
            input=[
                {
                    "call_id": computer_call.call_id,
                    "type": "computer_call_output",
                    "output": {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{screenshot_base64}"
                    }
                }
            ],
            truncation="auto"
        )

        # Recurse with the updated response
        return self.computer_use_loop(new_response)

    @property
    def current_response(self):
        """Get the current response object."""
        return self._current_response
        
    @property
    def response_history(self):
        """Get the history of all responses."""
        return self._response_history.copy()
        
    @property
    def input_history(self):
        """Get the history of all inputs."""
        return self._input_history.copy()
        
    @property
    def pending_call(self):
        """Get the pending computer call, if any."""
        return self._pending_call
        
    @property
    def pending_safety_checks(self):
        """Get the pending safety checks, if any."""
        return self._pending_safety_checks.copy() if self._pending_safety_checks else []
        
    @property
    def needs_input(self):
        """Get the messages requesting user input, if any."""
        return self._needs_input.copy() if self._needs_input else []
        
    @property
    def error(self):
        """Get the last error message, if any."""
        return self._error
        
    def reset_state(self):
        """Reset the agent's state, clearing all history and pending items."""
        self._response_history = []
        self._input_history = []
        self._current_response = None
        self._pending_call = None
        self._pending_safety_checks = []
        self._needs_input = []
        self._error = None
        
    def action(self, input_text=None, acknowledged_safety_checks=False):
        """
        Execute an action in the desktop environment. This method handles different scenarios:
        - Starting a new conversation with a command
        - Continuing a conversation with user input
        - Acknowledging safety checks for a pending call
        
        The method maintains state internally and returns a simple status and relevant data.
        
        Args:
            input_text: Text input from the user. This can be:
                       - A new command to start a conversation
                       - A response to an agent's request for input
                       - None if acknowledging safety checks
            acknowledged_safety_checks: Whether safety checks have been acknowledged
                                       (only relevant if there's a pending call)
        
        Returns:
            Tuple of (status, data), where:
            - status is an AgentStatus enum value indicating the result
            - data contains relevant information based on the status:
              - For COMPLETE: The final response object
              - For NEEDS_INPUT: List of messages requesting input
              - For NEEDS_SAFETY_CHECK: List of safety checks and the pending call
              - For ERROR: Error message
        """
        if self.desktop is None:
            self._error = "No desktop has been set for this agent."
            return AgentStatus.ERROR, self._error
            
        try:
            # Case 1: Acknowledging safety checks for a pending call
            if acknowledged_safety_checks and self._pending_call:
                return self._handle_acknowledged_safety_checks()
                
            # Case 2: Continuing a conversation with user input
            if self._needs_input and input_text is not None:
                return self._handle_user_input(input_text)
                
            # Case 3: Starting a new conversation with a command
            if input_text is not None:
                return self._handle_new_command(input_text)
                
            # If we get here, there's no valid action to take
            self._error = "No valid action to take. Provide input text or acknowledge safety checks."
            return AgentStatus.ERROR, self._error
                
        except Exception as e:
            self._error = str(e)
            return AgentStatus.ERROR, self._error
            
    def _handle_new_command(self, command_text):
        """Handle a new command from the user."""
        # Reset state for new conversation
        self._pending_call = None
        self._pending_safety_checks = []
        self._needs_input = []
        
        # Create input and response
        new_input = self._build_input_dict("user", command_text)
        self._input_history.append(new_input)
        
        response = self._create_response(new_input)
        self._response_history.append(response)
        self._current_response = response
        
        # Process the response
        return self._process_response(response)
        
    def _handle_user_input(self, input_text):
        """Handle user input in response to an agent request."""
        if not self._current_response:
            self._error = "No active conversation to continue."
            return AgentStatus.ERROR, self._error
            
        # Create input and response
        new_input = self._build_input_dict("user", input_text)
        self._input_history.append(new_input)
        
        response = self._create_response(new_input, previous_response_id=self._current_response.id)
        self._response_history.append(response)
        self._current_response = response
        
        # Clear the needs_input flag since we've provided input
        self._needs_input = []
        
        # Process the response
        return self._process_response(response)
        
    def _handle_acknowledged_safety_checks(self):
        """Handle acknowledged safety checks for a pending call."""
        if not self._current_response or not self._pending_call or not self._pending_safety_checks:
            self._error = "No pending call or safety checks to acknowledge."
            return AgentStatus.ERROR, self._error
            
        # Execute the call with acknowledged safety checks
        self._execute_and_continue_call(self._current_response, self._pending_call, self._pending_safety_checks)
        
        # Clear the pending call and safety checks
        self._pending_call = None
        self._pending_safety_checks = []
        
        # Process the updated response
        return self._process_response(self._current_response)
        
    def _process_response(self, response):
        """Process a response from the API and determine the next action."""
        output, messages, checks, pending_call = self.computer_use_loop(response)
        self._current_response = output
        
        # Update state based on the response
        if pending_call and checks:
            self._pending_call = pending_call
            self._pending_safety_checks = checks
            return AgentStatus.NEEDS_SAFETY_CHECK, {
                "safety_checks": checks,
                "pending_call": pending_call
            }
            
        if messages:
            self._needs_input = messages
            return AgentStatus.NEEDS_INPUT, messages
            
        # If we get here, the action is complete
        return AgentStatus.COMPLETE, output

    def _build_input_dict(self, role, content, checks=None):
        """
        Helper method to build an input dictionary for the OpenAI API.
        
        Args:
            role: The role of the message (e.g., "user", "assistant")
            content: The content of the message
            checks: Optional safety checks
            
        Returns:
            A dictionary with the message data
        """
        payload = {"role": role, "content": content}
        if checks:
            payload["safety_checks"] = checks
        return payload

    def _create_response(self, new_input, previous_response_id=None):
        """
        Helper method to create a response from the OpenAI API.
        
        Args:
            new_input: The input to send to the API
            previous_response_id: Optional ID of a previous response to continue from
            
        Returns:
            A response object from the OpenAI API
        """
        params = {
            "model": "computer-use-preview",
            "tools": [{
                "type": "computer_use_preview",
                "display_width": 1024,
                "display_height": 768,
                "environment": "linux"
            }],
            "input": [new_input],
            "truncation": "auto",
        }
        if previous_response_id is None:
            params["reasoning"] = {"generate_summary": "concise"}
        else:
            params["previous_response_id"] = previous_response_id
        return self.openai_client.responses.create(**params)

    def _execute_and_continue_call(self, input, computer_call, safety_checks):
        """
        Helper for 'action': directly executes a 'computer_call' after user acknowledged
        safety checks. Then performs the screenshot step, sending 'acknowledged_safety_checks'
        in the computer_call_output.
        
        Args:
            input: The input response object
            computer_call: The computer call to execute
            safety_checks: The safety checks that were acknowledged
        """
        if self.desktop is None:
            raise ValueError("No desktop has been set for this agent.")
            
        # Actually execute the call
        self.handle_model_action(computer_call.action)
        time.sleep(1)

        # Take a screenshot
        screenshot_base64 = self.desktop.get_screenshot()
        image_data = base64.b64decode(screenshot_base64)
        with open("output_image.png", "wb") as f:
            f.write(image_data)
        print("* Saved image data.")

        # Now, create a new response with an acknowledged_safety_checks field
        # in the computer_call_output
        new_response = self.openai_client.responses.create(
            model="computer-use-preview",
            previous_response_id=input.id,
            tools=[
                {
                    "type": "computer_use_preview",
                    "display_width": 1024,
                    "display_height": 768,
                    "environment": "linux"
                }
            ],
            input=[
                {
                    "call_id": computer_call.call_id,
                    "type": "computer_call_output",
                    "acknowledged_safety_checks": [
                        {
                            "id": check.id,
                            "code": check.code,
                            "message": getattr(check, "message", "Safety check message")
                        }
                        for check in safety_checks
                    ],
                    "output": {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{screenshot_base64}"
                    }
                }
            ],
            truncation="auto"
        )
        
        # Add to response history
        self._response_history.append(new_response)
        self._current_response = new_response

    def extract_and_print_safety_checks(self, result):
        """
        Extract and print safety checks from a result.
        
        Args:
            result: A result dictionary from an action
            
        Returns:
            A list of safety checks
        """
        checks = result.get("safety_checks") or []
        for check in checks:
            # If each check has a 'message' attribute with sub-parts
            if hasattr(check, "message"):
                # Gather text for printing
                print(f"Pending Safety Check: {check.message}")
        return checks

    def handle_action(self, action_input, stored_response=None, user_input=None):
        """
        Demo function to call and manage `action` loop and responses using the new state-based API.
        
        Args:
            action_input: The input to send to the agent
            stored_response: Optional stored response to continue from (deprecated, kept for compatibility)
            user_input: Optional user input to continue with (deprecated, kept for compatibility)
            
        Returns:
            The final result of the action
        
        1) Call the agent.action method to handle commands or continue interactions
        2) Print out agent prompts and safety checks
        3) If there's user input needed, prompt
        4) If there's a pending computer call with safety checks, ask user for ack, then continue
        5) Repeat until no further action is required
        """
        if self.desktop is None:
            raise ValueError("No desktop has been set for this agent.")
            
        print(
            "Performing desktop action... see output_image.png to see screenshots "
            "OR connect to the VNC server to view actions in real time"
        )

        # Start the chain - handle backward compatibility
        if user_input is not None:
            # This is a continuation with user input
            status, data = self.action(input_text=user_input)
        else:
            # This is a new command or stored response (stored_response is deprecated)
            command = action_input
            status, data = self.action(input_text=command)

        while True:
            # Handle different statuses
            if status == AgentStatus.NEEDS_INPUT:
                # Agent needs more input
                messages = data
                for msg in messages:
                    if hasattr(msg, "content"):
                        text_parts = [part.text for part in msg.content if hasattr(part, "text")]
                        print(f"Agent asks: {' '.join(text_parts)}")

                user_says = input("Enter your response (or 'exit'/'quit'): ").strip().lower()
                if user_says in ("exit", "quit"):
                    print("Exiting as per user request.")
                    return self.current_response

                # Call action again with the user input
                status, data = self.action(input_text=user_says)
                continue

            elif status == AgentStatus.NEEDS_SAFETY_CHECK:
                # Safety checks need acknowledgment
                safety_checks = data["safety_checks"]
                for check in safety_checks:
                    if hasattr(check, "message"):
                        print(f"Pending Safety Check: {check.message}")

                print("Please acknowledge the safety check(s) in order to proceed with the computer call.")
                ack = input("Type 'ack' to confirm, or 'exit'/'quit': ").strip().lower()
                if ack in ("exit", "quit"):
                    print("Exiting as per user request.")
                    return self.current_response
                if ack == "ack":
                    print("Acknowledged. Proceeding with the computer call...")
                    # Call action again with acknowledged safety checks
                    status, data = self.action(acknowledged_safety_checks=True)
                    continue

            elif status == AgentStatus.ERROR:
                # An error occurred
                print(f"Error: {data}")
                return self.current_response

            # If we get here, the action is complete
            return data
