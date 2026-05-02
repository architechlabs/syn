import json
from .models import ScenePlanRequest


def _entity_to_dict(entity):
    if isinstance(entity, dict):
        return entity
    if hasattr(entity, "model_dump"):
        return entity.model_dump()
    return entity.dict()


PROMPT_TEMPLATE = '''
You are a professional Home Assistant scene planner. Produce only valid JSON following the provided schema.

Room context:
{room}

Entities and capabilities:
{entities}

Capability/service contract:
- light: turn_on, turn_off, toggle. Use data keys brightness (0-255), color_temp_kelvin (Kelvin), rgb_color ([r,g,b]), effect, transition only when present in capabilities.
- For lights with effect support, use only effect + optional brightness. Do not combine effect with color_temp_kelvin, color_temp, rgb_color, or xy_color.
- If effect_list is present in state.attributes, choose an effect exactly from that list. Never invent effect names such as Cozy unless listed.
- switch: turn_on, turn_off, toggle. Do not add brightness, color, source, or volume data.
- media_player: turn_on, turn_off, volume_set, volume_mute, select_source, media_play, media_pause. Use volume_level (0.0-1.0), is_volume_muted, source, media_content_id, media_content_type only when supported by capabilities/state.
- fan: turn_on, turn_off, set_percentage, oscillate. Use percentage (0-100) or oscillating only when supported.

User intent:
{intent}

Constraints:
{constraints}

Output requirements:
- Return a JSON object with keys: scene_name, description, intent, target_room, actions, confidence, warnings, assumptions, entity_map
- actions must be a list of objects: entity_id, domain, service, data, rationale, priority
- Every action object must include entity_id exactly as listed above, for example "light.dining_pendant"; never use a friendly name in place of entity_id.
- entity_map must be an object keyed by entity_id. Each value must include entity_id, domain, and capabilities.
- Use only entity_id values listed above.
- Do not create actions for domains or devices that are not in the selected entities list.
- For a single light scene, return one light.turn_on action, not duplicates.
- For cozy/movie/night/relax prompts, use dim warm lighting: brightness 35-90 on the Home Assistant 0-255 scale when brightness is supported.
- For office/work/focus prompts, use clean neutral light: brightness 160-220 and color_temp_kelvin around 4000-4500 when supported.
- For party/disco prompts, use variety: RGB lights should get different saturated colors or supported dynamic effects. Do not make every RGB light white/yellow.
- For horror/scary prompts, use low red/purple/blue RGB colors or supported candle/fire/pulse effects. Do not use office/cozy white.
- Prefer fewer, reliable actions over many speculative ones.
- Put important setup actions first by using higher priority values.
- Rationale must describe the selected entity, not a guessed room or device.

Do not invent entities or capabilities. If an action cannot be performed, list it in warnings and either downgrade action safely or omit it.

Respond with JSON only.
'''


def build_prompt(request: ScenePlanRequest) -> str:
    room = request.room_id or "unspecified"
    entities = json.dumps(
        [_entity_to_dict(e) for e in request.entities],
        indent=2,
        sort_keys=True,
    )
    intent = (request.user_prompt or f"Create a scene for {room}").strip()
    constraints = json.dumps(request.constraints or {}, indent=2)
    return PROMPT_TEMPLATE.format(room=room, entities=entities, intent=intent, constraints=constraints)
