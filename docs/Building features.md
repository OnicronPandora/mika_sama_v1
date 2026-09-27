### Buiding features for Mika-sama Project

- Each feature is a model to handle specific things.

- Some feartures:
 + Singing: Ability to synthesize vocal to generate melody.
 + Gaming: Ability to play game
 + Vision inference: Ability to see and inference self 2D-model, chat overlay, etc

- Strategy: Acer (client) will handle these features. These feature will be triggered by event. Admin can manually triggered this up. After run these feature, these models push the result to LLM, except the Vision Feature.

Note: Feature models must not own or invoke the LLM. LLM just use for chat inference only.