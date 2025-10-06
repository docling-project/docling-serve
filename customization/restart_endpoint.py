import boto3
from time import gmtime, strftime

REGION = "us-east-1"
SAGEMAKER_URL = f"https://api.sagemaker.{REGION}.amazonaws.com"

sm_client = boto3.client(service_name='sagemaker', endpoint_url=SAGEMAKER_URL, region_name=REGION)
instance_type = 'ml.g5.4xlarge'
model_name = 'docling-serve-2025-09-04-03-09-07'  # Get this from endpoint settings, under the Production variants section
endpoint_name = "docling-serve-2025-09-04-03-09-08"

def create_endpoint_config(model_name):
    endpoint_config_name = 'docling-serve-' + strftime("%Y-%m-%d-%H-%M-%S", gmtime())
    print('Endpoint config name: ' + endpoint_config_name)

    create_endpoint_config_response = sm_client.create_endpoint_config(
        EndpointConfigName = endpoint_config_name,
        ProductionVariants=[{
            'InferenceAmiVersion': "al2-ami-sagemaker-inference-gpu-3-1",
            'InstanceType': instance_type,
            'InitialInstanceCount': 1,
            'InitialVariantWeight': 1,
            'ModelName': model_name,
            'VariantName': 'AllTraffic'}])
            
    print("Endpoint config Arn: " + create_endpoint_config_response['EndpointConfigArn'])
    return endpoint_config_name

def update_endpoint(endpoint_name, endpoint_config_name):
    print('Updating endpoint: ' + endpoint_name)
    update_endpoint_response = sm_client.update_endpoint(
        EndpointName=endpoint_name,
        EndpointConfigName=endpoint_config_name)
    print("Endpoint Arn: " + update_endpoint_response['EndpointArn'])
    return update_endpoint_response


endpoint_config_name = create_endpoint_config(model_name)
update_endpoint_response = update_endpoint(endpoint_name, endpoint_config_name)
