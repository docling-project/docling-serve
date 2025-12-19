import boto3
from time import gmtime, strftime

REGION = "us-east-1"
SAGEMAKER_URL = f"https://api.sagemaker.{REGION}.amazonaws.com"
IMAGE_VERSION = "v1.9.0"
STS_URL = f"https://sts.{REGION}.amazonaws.com"

sm_client = boto3.client(service_name='sagemaker', endpoint_url=SAGEMAKER_URL, region_name=REGION)

account_id = boto3.client('sts', endpoint_url=STS_URL).get_caller_identity()['Account']
instance_type = 'ml.g5.4xlarge'
# instance_type = 'ml.m5.xlarge'

#used to store model artifacts which SageMaker AI will extract to /opt/ml/model in the container, 
#in this example case we will not be making use of S3 to store the model artifacts
#s3_bucket = '<S3Bucket>'

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

def create_endpoint(endpoint_config_name):
    endpoint_name = 'docling-serve-' + strftime("%Y-%m-%d-%H-%M-%S", gmtime())
    print('Endpoint name: ' + endpoint_name)

    create_endpoint_response = sm_client.create_endpoint(
        EndpointName=endpoint_name,
        EndpointConfigName=endpoint_config_name)
    print('Endpoint Arn: ' + create_endpoint_response['EndpointArn'])

    resp = sm_client.describe_endpoint(EndpointName=endpoint_name)
    status = resp['EndpointStatus']
    print("Endpoint Status: " + status)

    print('Waiting for {} endpoint to be in service...'.format(endpoint_name))
    waiter = sm_client.get_waiter('endpoint_in_service')
    waiter.wait(EndpointName=endpoint_name)
    
model_name = create_model()
endpoint_config_name = create_endpoint_config(model_name)
create_endpoint(endpoint_config_name)