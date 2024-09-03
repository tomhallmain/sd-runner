This code is primarily a custom UI to trigger ComfyUI workflows or SD Web UI functions using presets and prompt randomization.

## Configuration Options

`gen_order`: A single run can include multiple resolutions, models, vaes, loras, IP adapters, and control nets. Modify the gen_order list to set the order in which these combinations are run.

`redo_parameters`: Redo an image using the stored workflow found in the image, but with desired different parameters.

`model_presets`: For specific models set clip_req and prompt_tags specific to prompt modes or generally.

`prompt_presets`: For specific prompt modes add a chance to prepend or append tokens to the prompt.

`prompt_presets_schedule`: Define an iteration schedule of named presets to be run via the UI.

`default_negative_prompt`: Any of the defaults are useful, but the negative default can be especially useful as it is often less likely to change.

## Prompt Syntax

Preset variables can be defined in the config to expand into full prompt text. To access these in the prompt UI, prepend $ or surround them with curly braces, and upon running the prompt the expansion will occur in the UI, overwriting the original prompt.

`"this is my $promptvar"` -> `"this is my expanded prompt text from promptvar"`

To use a variable without expanding it in the UI prompt, prepend two dollar signs instead of one.

`"this is my $$promptvar"` -> `"this is my $$promptvar"` (UI after starting a run) -> `this is my expanded prompt text from promptvar` (final prompt)

To define a set of words to randomly choose from, surround a comma-separated list with double square brackets, and one of the options will be chosen. All options are given equal choice weight of 1 unless one of the options has an appended colon at the end specifying the desired chance for the choice. The choice set will not be overwritten in the UI prompt.

`"A [[red,blue,yellow:2]] car"` -> `"A yellow car"`

Note that choice sets can be stored in preset prompt variables to cut down on visible prompt lengths.

## Prompt Presets

The presets window allows you to manage presets for specific prompt and prompt mode combinations. Use this window to add presets, delete presets and to apply them to the UI.

If a presets schedule is defined in the config, the checkbox Run Preset Schedule will be enabled and presets will be run at the specified schedule if this boolean is set to True.

## Concepts Folder

The prompts are generated using text concepts files. Each line in each file represents a concept that can be added randomly to the prompt, based on the prompter configuration.

A custom concepts folder can be defined by setting the `concepts_dir` config option. Restart the UI and select the new folder from the concepts dropdown to use this instead of the default concepts folder.

## Server

Set configuration options for a server port to make use of the server while the UI is running. Calls to the server made with Python's multiprocessing client will update the UI as specified, but leave anything unspecified as already set in the UI. This can be helpful to use in conjunction with other applications that involve images. For an example, see [this class](https://github.com/tomhallmain/simple_image_compare/blob/master/extensions/sd_runner_client.py).

## Notes

The stable-diffusion-webui img2img workflow is set up as the IP Adapter workflow. In this case, modifying the IP adapter strength in the UI will inversely modify the denoising strength to produce a similar effect as IP adapter strength would for that workflow.


