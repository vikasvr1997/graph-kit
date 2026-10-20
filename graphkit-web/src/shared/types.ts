export interface ModelInfo {
  id: string
  label: string
  validated: boolean
  notes: string
  dimensions?: string
}

export interface ModelsResponse {
  embedding_models: ModelInfo[]
  generation_models: ModelInfo[]
  defaults: { embedding_model: string; generation_model: string }
  note: string
}
