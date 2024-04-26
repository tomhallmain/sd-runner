This code is primarily a custom UI to trigger ComfyUI workflows using presets and prompt randomization.

## Configuration Options

`gen_order`: A single run can include multiple resolutions, models, vaes, loras, IP adapters, and control nets. Modify the gen_order list to set the order in which these combinations are run.

`redo_parameters`: Redo an image using the stored workflow found in the image, but with desired different parameters.

`model_presets`: For specific models set clip_req and prompt_tags specific to prompt modes or generally.

`prompt_presets`: For specific prompt modes add a chance to prepend or append tokens to the prompt.

`default_negative_prompt`: Any of the defaults are useful, but the negative default can be especially useful as it is often less likely to change.

