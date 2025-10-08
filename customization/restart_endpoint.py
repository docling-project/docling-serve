import boto3
from time import gmtime, strftime

REGION = "us-east-1"
SAGEMAKER_URL = f"https://api.sagemaker.{REGION}.amazonaws.com"
IMAGE_VERSION = "v1.5.1"
STS_URL = f"https://sts.{REGION}.amazonaws.com"

account_id = boto3.client('sts', endpoint_url=STS_URL).get_caller_identity()['Account']
sm_client = boto3.client(service_name='sagemaker', endpoint_url=SAGEMAKER_URL, region_name=REGION)
instance_type = 'ml.g5.4xlarge'
existing_model_name = 'docling-serve-2025-09-04-03-09-07'  # Get this from endpoint settings, under the Production variants section
endpoint_name = "docling-serve-2025-09-04-03-09-08"
role = f"arn:aws:iam::{account_id}:role/sagemaker-execution-role"

def create_model():
    model_name = 'docling-serve-' + strftime("%Y-%m-%d-%H-%M-%S", gmtime())
    # MODEL S3 URL containing model atrifacts as either model.tar.gz or extracted artifacts. 
    # Here we are not  
    #model_url = 's3://{}/spacy/'.format(s3_bucket) 

    container = '{}.dkr.ecr.{}.amazonaws.com/docling-sagemaker:{}'.format(account_id, REGION, IMAGE_VERSION)

    print('Model name: ' + model_name)
    #print('Model data Url: ' + model_url)
    print('Container image: ' + container)

    container = {
        'Image': container,
        'Environment': {
            'S3_MODEL_URI': f's3://{account_id}-sagemaker-models/app/models',
        }
    }

    create_model_response = sm_client.create_model(
        ModelName = model_name,
        ExecutionRoleArn = role,
        Containers = [container])

    print("Model Arn: " + create_model_response['ModelArn'])
    return model_name

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


model_name = create_model()
endpoint_config_name = create_endpoint_config(model_name)
update_endpoint_response = update_endpoint(endpoint_name, endpoint_config_name)
