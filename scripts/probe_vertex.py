"""Check model availability without sending source data."""
import json
from google import genai
from google.genai import types
client = genai.Client(vertexai=True, project='premium-odyssey-508202-k9', location='global',
                      http_options=types.HttpOptions(timeout=30000))
for model in ['gemini-3.5-flash', 'gemini-3-flash-preview', 'gemini-2.5-flash']:
    try:
        response = client.models.generate_content(model=model, contents='Return JSON {"ready":true}.',
            config=types.GenerateContentConfig(response_mime_type='application/json', temperature=0, max_output_tokens=128))
        print(json.dumps({'model': model, 'result': response.text}), flush=True)
        if response.text:
            open('graphkit_out/cloud_model.json','w').write(json.dumps({'model':model,'location':'global'}))
            break
    except Exception as e:
        print(json.dumps({'model':model,'error':str(e)[:1500]}), flush=True)
emb = genai.Client(vertexai=True, project='premium-odyssey-508202-k9', location='us-east1',
                   http_options=types.HttpOptions(timeout=30000))
try:
    result=emb.models.embed_content(model='gemini-embedding-001',contents='Customer metadata',
        config=types.EmbedContentConfig(task_type='RETRIEVAL_DOCUMENT',output_dimensionality=768))
    print('embedding_dimensions',len(result.embeddings[0].values),flush=True)
except Exception as e:
    print('embedding_error',str(e)[:1500],flush=True)
